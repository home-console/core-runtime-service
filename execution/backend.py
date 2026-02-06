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
class OperationEnvelope:
    operation_id: str
    operation_type: str
    params: Dict[str, Any]
    context: Dict[str, Any]
    # optional metadata for policy/debug; backend must ignore unknown keys
    metadata: Dict[str, Any] = None  # type: ignore[assignment]


@dataclass(frozen=True)
class OperationResult:
    ok: bool
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None
    backend: Optional[str] = None  # for debugging/inspector logs if needed


class ExecutionBackend(Protocol):
    async def execute(self, operation: OperationEnvelope) -> OperationResult: ...


class InProcessBackend:
    """
    In-process execution: вызывает уже зарегистрированный handler в текущем runtime.
    """

    def __init__(self, runtime: Any):
        self._runtime = runtime

    async def execute(self, operation: OperationEnvelope) -> OperationResult:
        ops_mgr = getattr(self._runtime, "operations", None)
        if ops_mgr is None:
            return OperationResult(
                ok=False,
                error={"code": "no_operations_manager", "message": "Operations manager not available"},
                backend="in_process",
            )

        # IMPORTANT: не используем ops_mgr.execute(), чтобы не зациклиться на execution layer.
        handlers = getattr(ops_mgr, "_handlers", {})
        handler = handlers.get(operation.operation_type)
        if handler is None:
            return OperationResult(
                ok=False,
                error={
                    "code": "unknown_operation_type",
                    "message": f"No handler for operation type: {operation.operation_type}",
                },
                backend="in_process",
            )

        try:
            result = await handler(
                operation.params,
                {"runtime": self._runtime, "operation_id": operation.operation_id, **(operation.context or {})},
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
    """
    Separate-process execution.

    В рамках D3 это backend-контракт + заглушка. Реальная реализация потребует
    рабочего процесса с загрузкой runtime/handlers и IPC протокола.
    """

    async def execute(self, operation: OperationEnvelope) -> OperationResult:
        return OperationResult(
            ok=False,
            error={
                "code": "not_implemented",
                "message": "Process backend is a D3 integration point; implementation is not shipped yet.",
            },
            backend="process",
        )


class ContainerBackend:
    """
    Container execution.

    В рамках D3 это backend-контракт + заглушка. Реальная реализация потребует
    docker/podman/k8s драйвера и протокола передачи operation envelope.
    """

    async def execute(self, operation: OperationEnvelope) -> OperationResult:
        return OperationResult(
            ok=False,
            error={
                "code": "not_implemented",
                "message": "Container backend is a D3 integration point; implementation is not shipped yet.",
            },
            backend="container",
        )

