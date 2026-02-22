"""
Execution backends (D3).

Backend знает КАК запускать, но не знает ЧТО он запускает (домены/automation/plugins).
Он получает envelope операции и должен вернуть OperationResult.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol, Literal
import asyncio


BackendId = Literal["in_process", "process", "container"]


@dataclass(frozen=True)
class OperationResult:
    """
    Результат исполнения операции backend'ом.

    Помимо бизнес-результата (result/error) содержит минимальные execution-метаданные,
    необходимые для observability-слоя (D3.3), но не тянет домен.
    """

    ok: bool
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None
    backend: Optional[str] = None  # for debugging/inspector logs if needed

    # Observability metadata (D3.3)
    stderr: Optional[str] = None
    killed: bool = False
    timed_out: bool = False


class ExecutionBackend(Protocol):
    async def execute(
        self,
        *,
        operation_type: str,
        params: Dict[str, Any],
        context: Dict[str, Any],
        timeout: int | None = None,
    ) -> OperationResult: ...

    async def cancel(self, execution_id: str) -> bool: ...


class InProcessBackend:
    """
    In-process execution: вызывает уже зарегистрированный handler в текущем runtime.
    """

    def __init__(self, runtime: Any):
        self._runtime = runtime
        # execution_id -> asyncio.Task
        self._tasks: Dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    async def execute(
        self,
        *,
        operation_type: str,
        params: Dict[str, Any],
        context: Dict[str, Any],
        timeout: int | None = None,
    ) -> OperationResult:
        ops_mgr = getattr(self._runtime, "operations", None)
        if ops_mgr is None:
            return OperationResult(
                ok=False,
                error={"code": "no_operations_manager", "message": "Operations manager not available"},
                backend="in_process",
            )

        # IMPORTANT: не используем ops_mgr.execute(), чтобы не зациклиться на execution layer.
        # Handlers хранятся в ops_mgr._registry, не в ops_mgr._handlers (OperationManager — фасад).
        handler = getattr(ops_mgr, "_find_handler", lambda _: None)(operation_type)
        if handler is None:
            return OperationResult(
                ok=False,
                error={
                    "code": "unknown_operation_type",
                    "message": f"No handler for operation type: {operation_type}",
                },
                backend="in_process",
            )

        exec_id = (context or {}).get("execution_id")

        async def _run() -> OperationResult:
            try:
                result = await handler(
                    params,
                    {"runtime": self._runtime, **(context or {})},
                )
                if not isinstance(result, Dict):
                    result = {"value": result}
                return OperationResult(ok=True, result=result, backend="in_process")
            except asyncio.CancelledError:
                # Пользовательский cancel через ExecutionController.cancel_execution
                return OperationResult(
                    ok=False,
                    error={"code": "cancelled", "message": "Execution cancelled"},
                    backend="in_process",
                )
            except Exception as e:
                return OperationResult(
                    ok=False,
                    error={"code": "execution_error", "message": str(e), "type": type(e).__name__},
                    backend="in_process",
                )

        task = asyncio.create_task(_run())
        if isinstance(exec_id, str):
            async with self._lock:
                self._tasks[exec_id] = task

        try:
            return await task
        finally:
            if isinstance(exec_id, str):
                async with self._lock:
                    self._tasks.pop(exec_id, None)

    async def cancel(self, execution_id: str) -> bool:
        """
        Best-effort отмена in-process исполнения по execution_id.
        """
        async with self._lock:
            task = self._tasks.get(execution_id)
        if task is None:
            return False
        task.cancel()
        return True


class ProcessBackend:
    def __init__(self) -> None:
        # Один реальный backend на все вызовы, чтобы можно было управлять процессами.
        from .backends.process import ProcessBackend as RealProcessBackend  # локальный импорт — это не Core

        self._real = RealProcessBackend()

    async def execute(
        self,
        *,
        operation_type: str,
        params: Dict[str, Any],
        context: Dict[str, Any],
        timeout: int | None = None,
    ) -> OperationResult:
        return await self._real.execute(
            operation_type=operation_type,
            params=params,
            context=context,
            timeout=timeout,
        )

    async def cancel(self, execution_id: str) -> bool:
        return await self._real.cancel(execution_id)


class ContainerBackend:
    """
    Container execution.

    В рамках D3 это backend-контракт + заглушка. Реальная реализация потребует
    docker/podman/k8s драйвера и протокола передачи operation envelope.
    """

    def __init__(self) -> None:
        from .backends.container import ContainerBackend as RealContainerBackend  # локальный импорт — это не Core

        self._real = RealContainerBackend()

    async def execute(
        self,
        *,
        operation_type: str,
        params: Dict[str, Any],
        context: Dict[str, Any],
        timeout: int | None = None,
    ) -> OperationResult:
        return await self._real.execute(
            operation_type=operation_type,
            params=params,
            context=context,
            timeout=timeout,
        )

    async def cancel(self, execution_id: str) -> bool:
        return await self._real.cancel(execution_id)

