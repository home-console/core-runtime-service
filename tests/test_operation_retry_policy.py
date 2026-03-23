import time
from unittest.mock import AsyncMock, Mock

import pytest

from core.execution.backend import OperationResult
from core.operations.executor import OperationExecutor
from core.operations.models import (
    Operation,
    OperationError,
    OperationInitiator,
    OperationInitiatorKind,
    OperationStatus,
)


@pytest.mark.asyncio
async def test_retryable_failure_schedules_next_retry(monkeypatch):
    registry = Mock()
    registry.find_handler.return_value = object()

    runtime = Mock()
    runtime.capability_registry = None
    runtime.execution_controller = Mock()
    runtime.execution_controller.execute_operation = AsyncMock(
        return_value=OperationResult(
            ok=False,
            error={"code": "timeout", "message": "temporary failure"},
            backend="in_process",
        )
    )

    storage = AsyncMock()
    storage.persist = AsyncMock()

    executor = OperationExecutor(registry, runtime, storage)

    monkeypatch.setattr("core.operations.executor.time.time", lambda: 1000.0)

    operation = Operation(
        operation_id="op-retry-1",
        op_type="test.retryable",
        params={},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
        max_retries=3,
    )

    result = await executor.execute(operation)

    assert result.status == OperationStatus.FAILED
    assert result.error is not None
    assert result.error.code == "timeout"
    assert result.retry_count == 1
    assert result.next_retry_at == 1001.0


@pytest.mark.asyncio
async def test_retry_is_skipped_until_due():
    registry = Mock()
    registry.find_handler.return_value = object()

    runtime = Mock()
    runtime.capability_registry = None
    runtime.execution_controller = Mock()
    runtime.execution_controller.execute_operation = AsyncMock()

    storage = AsyncMock()
    storage.persist = AsyncMock()

    executor = OperationExecutor(registry, runtime, storage)

    operation = Operation(
        operation_id="op-retry-2",
        op_type="test.retryable",
        params={},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
        max_retries=3,
        retry_count=1,
        next_retry_at=time.time() + 60,
    )
    operation.status = OperationStatus.FAILED
    operation.error = OperationError(code="timeout", message="temporary failure")

    result = await executor.execute(operation)

    assert result is operation
    assert result.status == OperationStatus.FAILED
    assert result.retry_count == 1
    assert result.next_retry_at is not None
    runtime.execution_controller.execute_operation.assert_not_called()
    storage.persist.assert_not_awaited()


def test_operation_retry_fields_round_trip():
    operation = Operation(
        operation_id="op-retry-3",
        op_type="test.retryable",
        params={"a": 1},
        initiator=OperationInitiator(kind=OperationInitiatorKind.ADMIN),
        max_retries=5,
        retry_count=2,
        next_retry_at=1234.5,
    )
    operation.status = OperationStatus.FAILED
    operation.error = OperationError(code="timeout", message="temporary failure")

    payload = operation.to_dict()
    restored = Operation.from_dict(payload)

    assert restored.retry_count == 2
    assert restored.max_retries == 5
    assert restored.next_retry_at == 1234.5
    assert restored.status == OperationStatus.FAILED
    assert restored.error is not None
    assert restored.error.code == "timeout"