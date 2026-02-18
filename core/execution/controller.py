"""
Execution controller (D3).

Controller:
- не знает домены
- не знает плагины (кроме optional metadata)
- не знает automation
- работает только с operation envelope + policy + backend registry
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Protocol
from uuid import uuid4
from datetime import datetime, UTC
import time
import asyncio

from .backend import BackendId, ExecutionBackend, InProcessBackend, ProcessBackend, ContainerBackend, OperationResult
from .policy import ExecutionPolicy, StateExecutionPolicy
from .trace import ExecutionTrace, ExecutionStatus, make_execution_namespace_keys


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
        # Простой счетчик для ограничений concurrency (D3.4)
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
        except Exception:
            pass
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
        except Exception:
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
            except Exception:
                # Observability не должен ломать execution
                pass

        # Events (optional, best-effort)
        event_bus = getattr(self._runtime, "event_bus", None)
        if event_bus is not None and hasattr(event_bus, "publish"):
            try:
                await event_bus.publish(
                    "execution.started",
                    {
                        "execution_id": trace.execution_id,
                        "operation_id": trace.operation_id,
                        "backend": trace.backend,
                        "status": trace.status,
                    },
                )
            except Exception:
                pass

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
            except Exception:
                pass

        event_bus = getattr(self._runtime, "event_bus", None)
        if event_bus is not None and hasattr(event_bus, "publish"):
            try:
                await event_bus.publish(
                    "execution.finished",
                    {
                        "execution_id": trace.execution_id,
                        "operation_id": trace.operation_id,
                        "backend": trace.backend,
                        "status": trace.status,
                    },
                )
            except Exception:
                pass

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
            except Exception:
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
        async with self._running_lock:
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

            # Грузим policy (async) и выбираем backend
            policy_dict = await self._load_policy()
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
                context={**context, "_execution_policy": metadata.get("_execution_policy")},
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

            await self.on_execution_finish(trace)

            return result
        finally:
            async with self._running_lock:
                self._running -= 1

