from __future__ import annotations

"""
ExecutionAdapter — единственная логика execution environment (runner side).

Он не знает Core, storage, policy, transport (docker/process/remote).
Он знает только:
- как найти handler по operation_type
- как вызвать handler
- как сериализовать результат в ExecutionResult
"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Protocol
import logging
logger = logging.getLogger(__name__)


class Handler(Protocol):
    def __call__(self, params: Dict[str, Any], context: Dict[str, Any]) -> Any: ...


@dataclass(frozen=True)
class ExecutionEnvelope:
    operation_type: str
    params: Dict[str, Any]
    context: Dict[str, Any]
    timeout: int | None = None


@dataclass(frozen=True)
class ExecutionError:
    code: str
    message: str
    details: Dict[str, Any] | None = None


@dataclass(frozen=True)
class ExecutionResult:
    status: str  # "ok" | "error"
    result: Dict[str, Any] | None = None
    error: ExecutionError | None = None


class ExecutionAdapter:
    def __init__(self, handlers: Mapping[str, Handler]) -> None:
        self._handlers = dict(handlers)

    def execute(self, envelope: ExecutionEnvelope) -> ExecutionResult:
        handler = self._handlers.get(envelope.operation_type)
        if handler is None:
            return ExecutionResult(
                status="error",
                error=ExecutionError(
                    code="unknown_operation_type",
                    message=f"Unknown operation type: {envelope.operation_type}",
                ),
            )

        try:
            value = handler(envelope.params or {}, envelope.context or {})
            # normalize to JSON-object
            if isinstance(value, dict):
                res = value
            else:
                res = {"value": value}
            return ExecutionResult(status="ok", result=res)
        except Exception as e:
            logger.warning("adapter.execute: failed: %s", e, exc_info=True)
            return ExecutionResult(
                status="error",
                error=ExecutionError(
                    code="execution_error",
                    message=str(e),
                    details={"type": type(e).__name__},
                ),
            )


def default_handlers() -> Dict[str, Handler]:
    """
    MVP handlers для smoke-test протокола.

    Это НЕ доменная логика: только тестовые операции.
    """

    def test_echo(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        return {"echo": params, "context": context}

    return {
        "test.echo": test_echo,
    }

