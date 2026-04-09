import asyncio
import pytest
from unittest.mock import AsyncMock, Mock

from core.operations.executor import OperationExecutor
import core.operations.executor as operations_executor_module
from core.operations.models import (
    Attempt,
    AttemptStatus,
    Operation,
    OperationError,
    OperationInitiator,
    OperationInitiatorKind,
    OperationStatus,
)


@pytest.mark.asyncio
async def test_executor_cancel_requested_stops_during_heartbeat(monkeypatch):
    runtime = Mock()
    runtime.operation_attempt_lease_ttl = 2
    runtime.service_registry = Mock()
    runtime.service_registry.call = AsyncMock()

    attempt_id = "attempt-1"
    claim_token = "claim-1"
    operation_id = "op-1"
    worker_id = "worker-1"

    attempt = Attempt(
        attempt_id=attempt_id,
        operation_id=operation_id,
        attempt_index=0,
        status=AttemptStatus.CLAIMED,
        claim_token=claim_token,
        execution_token=claim_token,
        claimed_at=0.0,
        lease_expires_at=10_000.0,
        claimed_by=worker_id,
        worker_id=worker_id,
        started_at=None,
    )

    operation = Operation(
        operation_id=operation_id,
        op_type="test.cancel",
        params={},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
    )
    operation.cancel_requested = False
    operation.timeout_seconds = None

    storage = Mock()
    storage.get_attempt = AsyncMock(return_value=attempt)
    storage.persist_attempt = AsyncMock()
    storage.get = AsyncMock(return_value=operation)
    storage.persist = AsyncMock()
    storage.extend_claim = AsyncMock(return_value=True)

    # runtime.storage.get:
    # - operation_results -> None
    # - operations -> cancel_requested flips to True
    op_current_calls = {"n": 0}

    async def _runtime_storage_get(namespace, key):
        if namespace == "operation_results":
            return None
        if namespace == "operations":
            op_current_calls["n"] += 1
            return {"cancel_requested": op_current_calls["n"] >= 1, "timeout_seconds": None}
        return None

    runtime.storage.get = AsyncMock(side_effect=_runtime_storage_get)
    runtime.storage.set = AsyncMock()

    executor = OperationExecutor(registry=Mock(), runtime=runtime, storage=storage)

    async def _fake_execute(_op):
        _op.status = OperationStatus.CANCELLED
        _op.error = OperationError(code="cancelled", message="cancelled")
        return _op

    executor.execute = _fake_execute  # type: ignore[method-assign]

    monkeypatch.setattr(operations_executor_module.time, "time", lambda: 1000.0)

    res = await executor.execute_attempt(attempt_id, claim_token)

    assert res.status == OperationStatus.CANCELLED
    assert attempt.status == AttemptStatus.CANCELLED
    assert runtime.storage.set.call_count == 0  # no operation_results write on cancel


@pytest.mark.asyncio
async def test_executor_timeout_stops_during_heartbeat(monkeypatch):
    runtime = Mock()
    runtime.operation_attempt_lease_ttl = 2
    runtime.service_registry = Mock()
    runtime.service_registry.call = AsyncMock()

    attempt_id = "attempt-2"
    claim_token = "claim-2"
    operation_id = "op-2"
    worker_id = "worker-2"

    attempt = Attempt(
        attempt_id=attempt_id,
        operation_id=operation_id,
        attempt_index=0,
        status=AttemptStatus.CLAIMED,
        claim_token=claim_token,
        execution_token=claim_token,
        claimed_at=0.0,
        lease_expires_at=10_000.0,
        claimed_by=worker_id,
        worker_id=worker_id,
    )

    operation = Operation(
        operation_id=operation_id,
        op_type="test.timeout",
        params={},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
    )
    operation.cancel_requested = False
    operation.timeout_seconds = 1

    storage = Mock()
    storage.get_attempt = AsyncMock(return_value=attempt)
    storage.persist_attempt = AsyncMock()
    storage.get = AsyncMock(return_value=operation)
    storage.persist = AsyncMock()
    storage.extend_claim = AsyncMock(return_value=True)

    async def _runtime_storage_get(namespace, key):
        if namespace == "operation_results":
            return None
        if namespace == "operations":
            # timeout is read from storage each heartbeat
            return {"cancel_requested": False, "timeout_seconds": 1}
        return None

    runtime.storage.get = AsyncMock(side_effect=_runtime_storage_get)
    runtime.storage.set = AsyncMock()

    executor = OperationExecutor(registry=Mock(), runtime=runtime, storage=storage)

    async def _fake_execute(_op):
        _op.status = OperationStatus.FAILED
        _op.error = OperationError(code="timeout", message="timed out")
        return _op

    executor.execute = _fake_execute  # type: ignore[method-assign]

    monkeypatch.setattr(operations_executor_module.time, "time", lambda: 1002.0)

    res = await executor.execute_attempt(attempt_id, claim_token)

    assert res.status == OperationStatus.FAILED
    assert res.error is not None
    assert res.error.code == "timeout"
    assert attempt.status == AttemptStatus.TIMEOUT
    assert runtime.storage.set.call_count == 0  # no operation_results write on timeout

