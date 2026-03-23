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
async def test_worker_executes_created_and_due_failed_operations():
    runtime = Mock()

    created_ready = Operation(
        operation_id="op-created-ready",
        op_type="test.created",
        params={},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
    )

    created_waiting = Operation(
        operation_id="op-created-waiting",
        op_type="test.created",
        params={},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
        next_retry_at=time.time() + 60,
    )

    failed_due = Operation(
        operation_id="op-failed-due",
        op_type="test.failed",
        params={},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
        retry_count=1,
        max_retries=3,
        next_retry_at=time.time() - 1,
    )
    failed_due.status = OperationStatus.FAILED
    failed_due.error = OperationError(code="timeout", message="temporary failure")

    runtime.operations = Mock()
    runtime.operations.list = AsyncMock(side_effect=[[created_ready, created_waiting], [failed_due]])
    runtime.operations.execute = AsyncMock()

    worker = OperationWorker(runtime)

    await worker.tick()

    assert runtime.operations.execute.await_count == 2
    executed_ids = [call.args[0].operation_id for call in runtime.operations.execute.await_args_list]
    assert executed_ids == ["op-created-ready", "op-failed-due"]


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