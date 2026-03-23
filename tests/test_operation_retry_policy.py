import time
from unittest.mock import AsyncMock, Mock

import pytest

from core.operations.worker import OperationWorker
from core.operations.models import (
    Operation,
    OperationError,
    OperationInitiator,
    OperationInitiatorKind,
    OperationStatus,
)
from modules.hooks.system import clear_system_hooks
from modules.retry_policy import RetryPolicyModule


@pytest.mark.asyncio
async def test_retryable_failure_schedules_next_retry(monkeypatch):
    clear_system_hooks()
    runtime = Mock()
    runtime.operations = Mock()
    runtime.operations._storage = Mock()
    runtime.operations._storage.ensure_attempt_created = AsyncMock()
    runtime.operations._storage.try_claim_attempt = AsyncMock(
        return_value=(True, "t1")
    )
    runtime.operations._storage.persist = AsyncMock()
    runtime.operations._executor = Mock()

    operation_created = Operation(
        operation_id="op-retry-1",
        op_type="test.retryable",
        params={},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
        max_retries=3,
    )

    after_failure = Operation(
        operation_id="op-retry-1",
        op_type="test.retryable",
        params={},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
        max_retries=3,
        retry_count=operation_created.retry_count,
        next_retry_at=operation_created.next_retry_at,
    )
    after_failure.status = OperationStatus.FAILED
    after_failure.error = OperationError(code="timeout", message="temporary failure")

    runtime.operations._executor.execute_attempt = AsyncMock(return_value=after_failure)

    module = RetryPolicyModule(runtime)
    await module.register()

    monkeypatch.setattr("core.operations.worker.time.time", lambda: 1000.0)

    worker = OperationWorker(runtime)
    result = await worker.execute_operation_now(operation_created)

    assert result.status == OperationStatus.FAILED
    assert result.error is not None
    assert result.error.code == "timeout"
    assert result.retry_count == 1
    assert result.next_retry_at == 1001.0


@pytest.mark.asyncio
async def test_retry_is_skipped_until_due():
    runtime = Mock()
    runtime.operations = Mock()
    runtime.operations._storage = Mock()
    runtime.operations._storage.ensure_attempt_created = AsyncMock()
    runtime.operations._storage.try_claim_attempt = AsyncMock(return_value=(True, "t1"))
    runtime.operations._storage.persist = AsyncMock()
    runtime.operations._executor = Mock()
    runtime.operations._executor.execute_attempt = AsyncMock()

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

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("core.operations.worker.time.time", lambda: 1000.0)
    worker = OperationWorker(runtime)
    try:
        result = await worker.execute_operation_now(operation)
    finally:
        monkeypatch.undo()

    assert result is operation
    assert result.status == OperationStatus.FAILED
    assert result.retry_count == 1
    assert result.next_retry_at is not None
    runtime.operations._executor.execute_attempt.assert_not_called()
    runtime.operations._storage.persist.assert_not_awaited()


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