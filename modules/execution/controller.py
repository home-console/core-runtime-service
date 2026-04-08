from __future__ import annotations

import logging
"""
Execution controller .

Controller:
- не знает домены
- не знает плагины (кроме optional metadata)
- не знает automation
- работает только с operation envelope + policy + backend registry
"""

from typing import Any, Dict, Optional, Protocol
from uuid import uuid4
from datetime import datetime, UTC
import time
import asyncio

from .backend import BackendId, ExecutionBackend, InProcessBackend, ProcessBackend, ContainerBackend, OperationResult
from .policy import ExecutionPolicy, StateExecutionPolicy
from core.adapters.storage_errors import STORAGE_BOUNDARY_ERRORS

from .trace import ExecutionTrace, ExecutionStatus, make_execution_namespace_keys
logger = logging.getLogger(__name__)


class ExecutionController(Protocol):
    async def execute_operation(
        self,
        operation_id: str,
        operation_type: str,
        params: dict,
        context: dict,
    ) -> OperationResult: ...


class ExecutionControllerImpl:
    def __init__(
        self,
        runtime: Any,
        policy: Optional[ExecutionPolicy] = None,
        backends: Optional[Dict[BackendId, ExecutionBackend]] = None,
        *,
        policy_storage_namespace: str = "execution",
        policy_storage_key: str = "policy",
    ):
        self._runtime = runtime
        self._policy = policy or StateExecutionPolicy(runtime)
        self._policy_ns = policy_storage_namespace
        self._policy_key = policy_storage_key

        self._backends: Dict[BackendId, ExecutionBackend] = backends or {
            "in_process": InProcessBackend(runtime),
            "process": ProcessBackend(),
            "container": ContainerBackend(),
        }

        # Конфигурация observability (можно сделать настраиваемой позднее)
        self._stderr_tail_max_chars: int = 4000
        # Простой счетчик для ограничений concurrency 
        self._running: int = 0
        self._running_lock = asyncio.Lock()

    async def _load_policy(self) -> Dict[str, Any]:
        """
        Загружает декларативный policy из storage, чтобы можно было менять без рестарта.
        """
        try:
            storage = getattr(self._runtime, "storage", None)
            if storage is None:
                return {}
            raw = await storage.get(self._policy_ns, self._policy_key)
            if isinstance(raw, dict):
                return raw
        except STORAGE_BOUNDARY_ERRORS:
            logger.warning(
                "execution: load policy from storage failed (boundary)", exc_info=True
            )
        except Exception:
            logger.warning("execution: load policy unexpected error", exc_info=True)
        return {}

    def _generate_execution_id(self) -> str:
        """
        Генерирует уникальный execution_id для одной попытки исполнения операции.

        Важно: execution_id ≠ operation_id. Одна операция может иметь несколько execution'ов.
        """
        return f"exec-{uuid4().hex[:12]}"

    async def _load_execution_trace(self, execution_id: str) -> Optional[ExecutionTrace]:
        storage = getattr(self._runtime, "storage", None)
        if storage is None:
            return None
        try:
            keys = make_execution_namespace_keys("", execution_id)
            data = await storage.get("execution", keys["trace_key"])
            if isinstance(data, dict):
                # operation_id внутри trace, поэтому operation_id в keys здесь не нужен
                return ExecutionTrace.from_dict(data)
        except STORAGE_BOUNDARY_ERRORS:
            logger.debug(
                "execution: load trace storage boundary (execution_id=%s)",
                execution_id,
                exc_info=True,
            )
            return None
        except Exception:
            logger.debug(
                "execution: load trace unexpected (execution_id=%s)",
                execution_id,
                exc_info=True,
            )
            return None
        return None

    async def on_execution_start(self, trace: ExecutionTrace) -> None:
        """
        Lifecycle hook: фиксируем старт исполнения.

        - Записываем trace со status="running" в namespace storage/execution
        - Пишем индекс по operation_id
        - Эмитим execution.started (best-effort)
        """
        storage = getattr(self._runtime, "storage", None)
        if storage is not None:
            try:
                keys = make_execution_namespace_keys(trace.operation_id, trace.execution_id)
                await storage.set("execution", keys["trace_key"], trace.to_dict())
                await storage.set(
                    "execution",
                    keys["index_key"],
                    {
                        "execution_id": trace.execution_id,
                        "operation_id": trace.operation_id,
                        "operation_type": trace.operation_type,
                        "backend": trace.backend,
                        "status": trace.status,
                        "started_at": trace.started_at.isoformat(),
                        "finished_at": trace.finished_at.isoformat() if trace.finished_at else None,
                        "duration_ms": trace.duration_ms,
                        "parent_execution_id": trace.parent_execution_id,
                        "retry_index": trace.retry_index,
                    },
                )
                # Lineage index (by_parent) — только если есть родитель
                if trace.parent_execution_id:
                    parent_key = f"by_parent/{trace.parent_execution_id}/{trace.execution_id}"
                    await storage.set(
                        "execution",
                        parent_key,
                        {
                            "execution_id": trace.execution_id,
                            "operation_id": trace.operation_id,
                            "operation_type": trace.operation_type,
                            "backend": trace.backend,
                            "status": trace.status,
                            "started_at": trace.started_at.isoformat(),
                            "finished_at": trace.finished_at.isoformat() if trace.finished_at else None,
                            "duration_ms": trace.duration_ms,
                            "retry_index": trace.retry_index,
                        },
                    )
            except STORAGE_BOUNDARY_ERRORS:
                logger.warning(
                    "execution.on_execution_start: persist trace storage boundary",
                    exc_info=True,
                )
            except Exception:
                logger.warning(
                    "execution.on_execution_start: persist trace unexpected",
                    exc_info=True,
                )

        # Events (optional, best-effort)
        event_bus = getattr(self._runtime, "event_bus", None)
        if event_bus is not None and hasattr(event_bus, "publish"):
            try:
                from core.events_schemas import ExecutionStartedPayload

                payload: ExecutionStartedPayload = {
                    "execution_id": trace.execution_id,
                    "operation_id": trace.operation_id,
                    "backend": trace.backend,
                    "status": trace.status,
                }
                await event_bus.publish(
                    "execution.started",
                    payload,
                )
            except Exception:
                logger.debug(
                    "execution.on_execution_start: event_bus.publish failed",
                    exc_info=True,
                )

    async def on_execution_finish(self, trace: ExecutionTrace) -> None:
        """
        Lifecycle hook: фиксируем завершение исполнения.

        - Обновляем trace (status, finished_at, duration_ms, error_*)
        - Обновляем индекс по operation_id
        - Эмитим execution.finished (best-effort)
        """
        storage = getattr(self._runtime, "storage", None)
        if storage is not None:
            try:
                keys = make_execution_namespace_keys(trace.operation_id, trace.execution_id)
                await storage.set("execution", keys["trace_key"], trace.to_dict())
                await storage.set(
                    "execution",
                    keys["index_key"],
                    {
                        "execution_id": trace.execution_id,
                        "operation_id": trace.operation_id,
                        "operation_type": trace.operation_type,
                        "backend": trace.backend,
                        "status": trace.status,
                        "started_at": trace.started_at.isoformat(),
                        "finished_at": trace.finished_at.isoformat() if trace.finished_at else None,
                        "duration_ms": trace.duration_ms,
                        "parent_execution_id": trace.parent_execution_id,
                        "retry_index": trace.retry_index,
                    },
                )
                if trace.parent_execution_id:
                    parent_key = f"by_parent/{trace.parent_execution_id}/{trace.execution_id}"
                    await storage.set(
                        "execution",
                        parent_key,
                        {
                            "execution_id": trace.execution_id,
                            "operation_id": trace.operation_id,
                            "operation_type": trace.operation_type,
                            "backend": trace.backend,
                            "status": trace.status,
                            "started_at": trace.started_at.isoformat(),
                            "finished_at": trace.finished_at.isoformat() if trace.finished_at else None,
                            "duration_ms": trace.duration_ms,
                            "retry_index": trace.retry_index,
                        },
                    )
            except STORAGE_BOUNDARY_ERRORS:
                logger.warning(
                    "execution.on_execution_finish: persist trace storage boundary",
                    exc_info=True,
                )
            except Exception:
                logger.warning(
                    "execution.on_execution_finish: persist trace unexpected",
                    exc_info=True,
                )

        event_bus = getattr(self._runtime, "event_bus", None)
        if event_bus is not None and hasattr(event_bus, "publish"):
            try:
                from core.events_schemas import ExecutionFinishedPayload

                payload: ExecutionFinishedPayload = {
                    "execution_id": trace.execution_id,
                    "operation_id": trace.operation_id,
                    "backend": trace.backend,
                    "status": trace.status,
                }
                await event_bus.publish(
                    "execution.finished",
                    payload,
                )
            except Exception:
                logger.debug(
                    "execution.on_execution_finish: event_bus.publish failed",
                    exc_info=True,
                )

    def _map_status_from_result(self, res: OperationResult) -> ExecutionStatus:
        if res.ok:
            return "ok"
        if getattr(res, "timed_out", False):
            return "timeout"
        if getattr(res, "killed", False):
            return "killed"

        err = res.error or {}
        code = err.get("code")
        if code == "timeout":
            return "timeout"
        if code == "cancelled":
            return "cancelled"
        return "error"

    def _extract_error_fields(self, res: OperationResult) -> Dict[str, Optional[str]]:
        if res.ok or not res.error:
            return {"code": None, "message": None}

        err = res.error
        code = err.get("code")
        message = err.get("message")
        return {"code": str(code) if code is not None else None, "message": str(message) if message is not None else None}

    def _extract_stderr_tail(self, res: OperationResult) -> Optional[str]:
        stderr = getattr(res, "stderr", None)
        if not stderr:
            # fallback: иногда stderr лежит в error.details.stderr
            try:
                details = (res.error or {}).get("details") or {}
                if isinstance(details, dict):
                    stderr = details.get("stderr")
            except (TypeError, AttributeError, KeyError):
                stderr = None
        if not stderr:
            return None
        tail = stderr[-self._stderr_tail_max_chars :]
        return tail

    async def execute_operation(
        self,
        operation_id: str,
        operation_type: str,
        params: dict,
        context: dict,
    ) -> OperationResult:
        """
        Главная точка входа ExecutionLayer.

        Гарантии:
        - не бросает исключения наружу (всегда OperationResult)
        - пишет ExecutionTrace в storage (best-effort)
        - эмитит события execution.started/execution.finished (best-effort)
        """
        # Глобальный concurrency-лимит (MVP): чтобы не уронить Core при наплыве задач.
        # Проверяем лимит max_running из policy
        policy_dict = await self._load_policy()
        limits = policy_dict.get("limits") or {}
        max_running = limits.get("max_running")

        async with self._running_lock:
            if max_running is not None and self._running >= int(max_running):
                # Лимит превышен — создаём trace с ошибкой и возвращаем
                execution_id = context.get("execution_id") or self._generate_execution_id()
                started_at_dt = datetime.now(UTC)
                trace = ExecutionTrace(
                    execution_id=execution_id,
                    operation_id=operation_id,
                    operation_type=operation_type,
                    backend="in_process",
                    status="error",
                    started_at=started_at_dt,
                    finished_at=started_at_dt,
                    duration_ms=0,
                    error_code="execution_limit_exceeded",
                    error_message=f"Concurrency limit exceeded: max_running={max_running}",
                    stderr_tail=None,
                    parent_execution_id=context.get("parent_execution_id"),
                    retry_index=int(context.get("retry_index") or 0),
                )
                await self.on_execution_start(trace)
                await self.on_execution_finish(trace)
                return OperationResult(
                    ok=False,
                    error={"code": "execution_limit_exceeded", "message": f"Concurrency limit exceeded: max_running={max_running}"},
                    backend="in_process",
                )
            self._running += 1

        started_at = time.time()
        try:
            execution_id = context.get("execution_id") or self._generate_execution_id()

            # Подготовим ExecutionTrace
            trace = ExecutionTrace(
                execution_id=execution_id,
                operation_id=operation_id,
                operation_type=operation_type,
                backend="in_process",  # заполним позже, когда выберем backend
                status="running",
                started_at=datetime.now(UTC),
                finished_at=None,
                duration_ms=None,
                error_code=None,
                error_message=None,
                stderr_tail=None,
                parent_execution_id=context.get("parent_execution_id"),
                retry_index=int(context.get("retry_index") or 0),
            )

            # Сначала пишем старт trace
            await self.on_execution_start(trace)

            # Грузим policy (уже загружен выше, переиспользуем)
            ctx_metadata = context.get("metadata") or {}
            metadata = dict(ctx_metadata)
            metadata["_execution_policy"] = policy_dict or {}

            plugin_name = context.get("plugin_name")
            backend_id = self._policy.select_backend(
                operation_type=operation_type,
                plugin_name=plugin_name,
                metadata=metadata,
            )
            backend = self._backends.get(backend_id) or self._backends["in_process"]
            trace.backend = backend_id

            # Выполняем операцию через backend
            result = await backend.execute(
                operation_type=operation_type,
                params=params,
                context={**context, "execution_id": execution_id, "_execution_policy": metadata.get("_execution_policy")},
                timeout=context.get("timeout"),
            )

            # Обновляем trace по результату
            trace.status = self._map_status_from_result(result)
            trace.finished_at = datetime.now(UTC)
            trace.duration_ms = int((time.time() - started_at) * 1000)
            err_fields = self._extract_error_fields(result)
            trace.error_code = err_fields["code"]
            trace.error_message = err_fields["message"]
            trace.stderr_tail = self._extract_stderr_tail(result)

            # Если отменена — фиксируем cancelled_at, но только если cancel_execution
            # ещё не выставил их (во избежание перезатирания reason)
            if trace.status == "cancelled":
                # Пробуем загрузить актуальный trace из storage
                stored_trace = await self._load_execution_trace(execution_id)
                if stored_trace is not None and stored_trace.cancelled_at is not None:
                    # cancel_execution уже обновил — берём его значения
                    trace.cancelled_at = stored_trace.cancelled_at
                    trace.cancel_reason = stored_trace.cancel_reason
                else:
                    trace.cancelled_at = datetime.now(UTC)
                    trace.cancel_reason = "cancelled"

            await self.on_execution_finish(trace)

            return result
        finally:
            async with self._running_lock:
                self._running -= 1

    async def cancel_execution(self, execution_id: str, reason: str = "user") -> bool:
        """
        Отменяет выполняющийся execution по execution_id.

        - Вызывает backend.cancel(execution_id)
        - Обновляет trace: status=cancelled, cancelled_at, cancel_reason
        """
        # Пробуем отменить задачу в каждом backend
        cancelled = False
        for backend in self._backends.values():
            if hasattr(backend, "cancel"):
                try:
                    result = await backend.cancel(execution_id)
                    if result:
                        cancelled = True
                        break
                except Exception:
                    logger.debug(
                        "execution.cancel_execution: backend.cancel failed "
                        "(backend=%s)",
                        type(backend).__name__,
                        exc_info=True,
                    )

        # Обновляем trace в storage
        trace = await self._load_execution_trace(execution_id)
        if trace is not None:
            trace.status = "cancelled"
            trace.cancelled_at = datetime.now(UTC)
            trace.cancel_reason = reason
            if trace.finished_at is None:
                trace.finished_at = datetime.now(UTC)
            await self.on_execution_finish(trace)

        return cancelled

    async def retry_execution(self, execution_id: str) -> OperationResult:
        """
        Создаёт повторное выполнение (retry) для завершённого execution.

        - Загружает оригинальный trace по execution_id
        - Если execution ещё running — возвращает ошибку
        - Проверяет ограничения retry policy
        - Запускает новый execute_operation с parent_execution_id и retry_index+1
        """
        trace = await self._load_execution_trace(execution_id)
        if trace is None:
            return OperationResult(
                ok=False,
                error={"code": "execution_not_found", "message": f"Execution {execution_id} not found"},
                backend="in_process",
            )

        if trace.status == "running":
            return OperationResult(
                ok=False,
                error={"code": "execution_still_running", "message": f"Execution {execution_id} is still running"},
                backend="in_process",
            )

        # Проверяем retry policy
        policy_dict = await self._load_policy()
        retry_policy = policy_dict.get("retry") or {}
        max_attempts = retry_policy.get("max_attempts")
        if max_attempts is not None:
            # Считаем сколько реальных retry уже произошло через by_parent индекс
            try:
                storage = getattr(self._runtime, "storage", None)
                if storage is not None:
                    all_keys = await storage.list_keys("execution")
                    existing_retries = [k for k in all_keys if k.startswith(f"by_parent/{execution_id}/")]
                    if len(existing_retries) >= int(max_attempts):
                        return OperationResult(
                            ok=False,
                            error={"code": "retry_limit_exceeded", "message": f"Retry limit exceeded: max_attempts={max_attempts}"},
                            backend="in_process",
                        )
            except STORAGE_BOUNDARY_ERRORS:
                logger.warning(
                    "execution.retry_execution: list_keys storage boundary",
                    exc_info=True,
                )
            except Exception:
                logger.warning(
                    "execution.retry_execution: retry policy check failed",
                    exc_info=True,
                )

        # Создаём новый execution с расширенным контекстом
        new_retry_index = trace.retry_index + 1
        context = {
            "parent_execution_id": execution_id,
            "retry_index": new_retry_index,
        }

        return await self.execute_operation(
            operation_id=trace.operation_id,
            operation_type=trace.operation_type,
            params={},  # оригинальные params не хранятся в trace, выполняем с пустыми
            context=context,
        )

