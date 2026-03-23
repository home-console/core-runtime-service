import asyncio
import time
from unittest.mock import AsyncMock, Mock

import pytest

from core.operations.models import (
    Operation,
    OperationError,
    OperationInitiator,
    OperationInitiatorKind,
    OperationStatus,
)
from core.operations.worker import OperationWorker
from core.runtime.runtime import CoreRuntime


@pytest.mark.asyncio
async def test_worker_executes_created_and_due_failed_operations(monkeypatch):
    monkeypatch.setattr("core.operations.worker.time.time", lambda: 1000.0)
    runtime = Mock()

    created_ready = Operation(
        operation_id="op-created-ready",
        op_type="test.created",
        params={},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
    )

    failed_due = Operation(
        operation_id="op-failed-due",
        op_type="test.failed",
        params={},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
        retry_count=1,
        max_retries=3,
        next_retry_at=-2600.0,
    )
    failed_due.status = OperationStatus.FAILED
    failed_due.error = OperationError(code="timeout", message="temporary failure")

    runtime.operations = Mock()
    runtime.operations.list = AsyncMock(side_effect=[[created_ready], [failed_due]])
    runtime.operations._storage = Mock()
    runtime.operations._storage.ensure_attempt_created = AsyncMock()
    runtime.operations._storage.try_claim_attempt = AsyncMock(
        side_effect=[(True, "t1"), (True, "t2")]
    )
    runtime.operations._storage.persist = AsyncMock()
    runtime.operations._executor = Mock()

    created_ready_completed = Operation(
        operation_id="op-created-ready",
        op_type="test.created",
        params={},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
    )
    created_ready_completed.status = OperationStatus.COMPLETED
    runtime.operations._executor.execute_attempt = AsyncMock(
        side_effect=[created_ready_completed, failed_due]
    )

    worker = OperationWorker(runtime)

    await worker.tick()

    assert runtime.operations._executor.execute_attempt.await_count == 2
    attempt_ids = [call.args[0] for call in runtime.operations._executor.execute_attempt.await_args_list]
    claim_tokens = [call.args[1] for call in runtime.operations._executor.execute_attempt.await_args_list]
    assert attempt_ids == [
        "attempt-op-created-ready-i0",
        "attempt-op-failed-due-i1",
    ]
    assert claim_tokens == ["t1", "t2"]


@pytest.mark.asyncio
async def test_runtime_start_wires_operation_worker(monkeypatch, memory_adapter):
    monkeypatch.setenv("TEST_MODE", "1")

    runtime = CoreRuntime(memory_adapter)

    runtime.module_manager.check_required_modules_registered = Mock()
    runtime.module_manager.start_all = AsyncMock()
    runtime.module_manager.stop_all = AsyncMock()
    runtime.plugin_manager.list_plugins = AsyncMock(return_value=[])
    runtime.plugin_manager.start_all = AsyncMock()
    runtime.plugin_manager.stop_all = AsyncMock()
    runtime.dependency_resolver.validate_runtime_integrity = Mock(return_value=[])

    await runtime.start()
    await asyncio.sleep(0)

    assert runtime.worker is not None
    assert runtime.worker.running is True
    assert runtime._worker_task is not None
    assert not runtime._worker_task.done()

    await runtime.stop()
