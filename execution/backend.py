"""
Execution backends (D3).

Backend знает КАК запускать, но не знает ЧТО он запускает (домены/automation/plugins).
Он получает envelope операции и должен вернуть OperationResult.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol, Literal


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


class InProcessBackend:
    """
    In-process execution: вызывает уже зарегистрированный handler в текущем runtime.
    """

    def __init__(self, runtime: Any):
        self._runtime = runtime

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
        handlers = getattr(ops_mgr, "_handlers", {})
        handler = handlers.get(operation_type)
        if handler is None:
            return OperationResult(
                ok=False,
                error={
                    "code": "unknown_operation_type",
                    "message": f"No handler for operation type: {operation_type}",
                },
                backend="in_process",
            )

        try:
            result = await handler(
                params,
                {"runtime": self._runtime, **(context or {})},
            )
            if not isinstance(result, dict):
                result = {"value": result}
            return OperationResult(ok=True, result=result, backend="in_process")
        except Exception as e:
            return OperationResult(
                ok=False,
                error={"code": "execution_error", "message": str(e), "type": type(e).__name__},
                backend="in_process",
            )


class ProcessBackend:
    async def execute(
        self,
        *,
        operation_type: str,
        params: Dict[str, Any],
        context: Dict[str, Any],
        timeout: int | None = None,
    ) -> OperationResult:
        # Реализация живёт в execution/backends/process.py, чтобы backend слой был расширяемым.
        from .backends.process import ProcessBackend as RealProcessBackend  # локальный импорт — это не Core

        return await RealProcessBackend().execute(
            operation_type=operation_type,
            params=params,
            context=context,
            timeout=timeout,
        )


class ContainerBackend:
    """
    Container execution.

    В рамках D3 это backend-контракт + заглушка. Реальная реализация потребует
    docker/podman/k8s драйвера и протокола передачи operation envelope.
    """

    async def execute(
        self,
        *,
        operation_type: str,
        params: Dict[str, Any],
        context: Dict[str, Any],
        timeout: int | None = None,
    ) -> OperationResult:
        # Реализация живёт в execution/backends/container.py (чтобы было проще расширять бэкенды).
        from .backends.container import ContainerBackend as RealContainerBackend  # локальный импорт — это не Core

        return await RealContainerBackend().execute(
            operation_type=operation_type,
            params=params,
            context=context,
            timeout=timeout,
        )

