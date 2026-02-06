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
from datetime import datetime
import time

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

    async def on_execution_start(self, trace: ExecutionTrace) -> None:
        """
        Lifecycle hook: фиксируем старт исполнения.

        - Записываем trace со status=\"running\" в namespace storage/execution
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

        if not stderr or not isinstance(stderr, str):
            return None
        if len(stderr) <= self._stderr_tail_max_chars:
            return stderr
        return stderr[-self._stderr_tail_max_chars :]

    async def execute_operation(
        self,
        operation_id: str,
        operation_type: str,
        params: dict,
        context: dict,
    ) -> OperationResult:
        # controller не должен делать доменные вызовы; только policy+backend+observability
        policy_dict = await self._load_policy()

        metadata: Dict[str, Any] = {
            "_execution_policy": policy_dict,
        }

        plugin_name = None
        try:
            plugin_name = (context or {}).get("plugin_name")
        except Exception:
            plugin_name = None

        backend_id = self._policy.select_backend(operation_type, plugin_name, metadata)
        backend = self._backends.get(backend_id)
        if backend is None:
            return OperationResult(
                ok=False,
                error={"code": "unknown_backend", "message": f"Unknown backend: {backend_id}"},
                backend=str(backend_id),
            )

        execution_id = self._generate_execution_id()
        started_at_dt = datetime.utcnow()
        started_monotonic = time.monotonic()

        trace = ExecutionTrace(
            execution_id=execution_id,
            operation_id=operation_id,
            operation_type=operation_type,
            backend=backend_id,
            status="running",
            started_at=started_at_dt,
            finished_at=None,
            duration_ms=None,
            error_code=None,
            error_message=None,
            stderr_tail=None,
        )

        await self.on_execution_start(trace)

        # Backend работает только с envelope операции (operation_type/params/context).
        # Policy dict прокидываем через context, чтобы backend мог (опционально) читать свои настройки,
        # не делая запросов к storage и не ломая границы слоёв.
        ctx = dict(context or {})
        ctx.setdefault("operation_id", operation_id)
        ctx.setdefault("_execution_policy", policy_dict)
        ctx.setdefault("execution_id", execution_id)

        try:
            res = await backend.execute(
                operation_type=operation_type,
                params=params or {},
                context=ctx,
                timeout=None,
            )
        except Exception as e:
            # Любая ошибка бэкенда тоже должна отражаться в трассе
            finished_at_dt = datetime.utcnow()
            duration_ms = int((time.monotonic() - started_monotonic) * 1000)
            trace.status = "error"
            trace.finished_at = finished_at_dt
            trace.duration_ms = duration_ms
            trace.error_code = "backend_exception"
            trace.error_message = str(e)
            trace.stderr_tail = None
            await self.on_execution_finish(trace)

            return OperationResult(
                ok=False,
                error={"code": "backend_exception", "message": str(e), "type": type(e).__name__},
                backend=str(backend_id),
            )

        # Успешное завершение backend'а (ok или ошибка уровня исполнения)
        finished_at_dt = datetime.utcnow()
        duration_ms = int((time.monotonic() - started_monotonic) * 1000)

        status: ExecutionStatus = self._map_status_from_result(res)
        err_fields = self._extract_error_fields(res)
        stderr_tail = self._extract_stderr_tail(res)

        trace.status = status
        trace.finished_at = finished_at_dt
        trace.duration_ms = duration_ms
        trace.error_code = err_fields["code"]
        trace.error_message = err_fields["message"]
        trace.stderr_tail = stderr_tail

        await self.on_execution_finish(trace)

        return res

