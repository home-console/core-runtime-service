"""
OperationExecutor - deterministic operation execution pipeline.
"""

from __future__ import annotations

import inspect
import time
from typing import Any

from core.operations.interface import IOperationExecutor
from core.operations.models import AttemptStatus, Operation, OperationError, OperationStatus
from core.operations.registry import OperationHandlerRegistry


class OperationExecutor(IOperationExecutor):
    def __init__(
        self,
        registry: OperationHandlerRegistry,
        runtime: Any,
        storage: Any,
    ) -> None:
        self.registry = registry
        self.runtime = runtime
        self.storage = storage

    def resolve_handler(self, operation: Operation):
        return self.registry.find_handler(operation.type)

    def _build_handler_context(self, operation: Operation) -> dict[str, Any]:
        return {
            "runtime": self.runtime,
            "operation": operation,
            "operation_id": operation.operation_id,
        }

    async def _invoke_handler(self, handler: Any, operation: Operation) -> Any:
        sig = inspect.signature(handler)
        params = list(sig.parameters.values())
        context = self._build_handler_context(operation)

        candidates: list[tuple[Any, ...]] = []
        if not params:
            candidates.append(())
        elif len(params) == 1:
            pname = params[0].name
            if pname in {"operation", "op"}:
                candidates.append((operation,))
            candidates.append((operation.params,))
        else:
            first_name = params[0].name
            second_name = params[1].name
            if first_name in {"runtime", "rt"} or second_name in {"operation", "op"}:
                candidates.append((self.runtime, operation))
            candidates.append((operation.params, context))
            candidates.append((self.runtime, operation))

        if not candidates:
            candidates.append((self.runtime, operation))

        last_error: Exception | None = None
        for args in candidates:
            try:
                maybe_result = handler(*args)
            except TypeError as exc:
                last_error = exc
                continue
            if inspect.isawaitable(maybe_result):
                return await maybe_result
            return maybe_result

        raise RuntimeError(
            f"Handler invocation failed for operation type '{operation.type}': {last_error}"
        )

    async def execute(self, operation: Operation) -> Operation:
        operation.status = OperationStatus.RUNNING
        operation.started_at = time.time()
        operation.error = None
        operation.result = None
        await self.storage.persist(operation)

        try:
            handler = self.resolve_handler(operation)
            if handler is None:
                raise LookupError(f"No handler for operation type: {operation.type}")

            maybe_result = await self._invoke_handler(handler, operation)

            if isinstance(maybe_result, Operation):
                operation = maybe_result
            else:
                operation.result = (
                    maybe_result if isinstance(maybe_result, dict) else {"value": maybe_result}
                )
                if operation.status == OperationStatus.RUNNING:
                    operation.status = OperationStatus.COMPLETED
        except Exception as exc:
            operation.status = OperationStatus.FAILED
            if operation.error is None:
                operation.error = OperationError(
                    code="failed",
                    message=str(exc),
                    details={"exception_type": type(exc).__name__},
                )

        operation.finished_at = time.time()
        await self.storage.persist(operation)
        return operation

    async def execute_attempt(
        self,
        attempt_id: str,
        claim_token: str,
        *,
        lease_guard_epsilon_s: float = 0.0,
    ) -> Operation:
        del lease_guard_epsilon_s

        attempt = await self.storage.get_attempt(attempt_id)
        if attempt is None:
            raise ValueError(f"Attempt not found: {attempt_id}")

        operation = await self.storage.get(attempt.operation_id)
        if operation is None:
            raise ValueError(f"Operation not found for attempt: {attempt.operation_id}")

        if attempt.status != AttemptStatus.CLAIMED:
            return operation
        if attempt.claim_token != claim_token:
            return operation

        attempt.status = AttemptStatus.RUNNING
        attempt.started_at = time.time()
        attempt.error = None
        await self.storage.persist_attempt(attempt)

        result = await self.execute(operation)

        if result.status == OperationStatus.COMPLETED:
            attempt.status = AttemptStatus.COMPLETED
            attempt.error = None
        elif result.status == OperationStatus.CANCELLED:
            attempt.status = AttemptStatus.CANCELLED
            attempt.error = result.error.to_dict() if result.error else None
        elif result.error is not None and result.error.code == AttemptStatus.TIMEOUT.value:
            attempt.status = AttemptStatus.TIMEOUT
            attempt.error = result.error.to_dict()
        else:
            attempt.status = AttemptStatus.FAILED
            attempt.error = result.error.to_dict() if result.error else None

        attempt.finished_at = time.time()
        await self.storage.persist_attempt(attempt)
        return result
