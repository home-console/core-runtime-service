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
from modules.hooks.runtime_contract import ensure_runtime_execution_contract
from core.operations.dedup import DedupLayer


@pytest.mark.asyncio
async def test_worker_executes_runnable_operations_from_operation_source(monkeypatch):
    monkeypatch.setattr("core.operations.worker.time.time", lambda: 1000.0)
    runtime = Mock()

    created_ready = Operation(
        operation_id="op-created-ready",
        op_type="test.created",
        params={},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
    )

    runtime.operations = Mock()
    runtime.operations.list = AsyncMock(return_value=[created_ready])
    runtime.operations._storage = Mock()
    runtime.operations._storage.ensure_attempt_created = AsyncMock()
    runtime.operations._storage.try_claim_attempt = AsyncMock(return_value=(True, "t1"))
    runtime.operations._storage.persist = AsyncMock()
    runtime.operations._executor = Mock()

    created_ready_completed = Operation(
        operation_id="op-created-ready",
        op_type="test.created",
        params={},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
    )
    created_ready_completed.status = OperationStatus.COMPLETED
    runtime.operations._executor.execute_attempt = AsyncMock(return_value=created_ready_completed)
    ensure_runtime_execution_contract(runtime)

    worker = OperationWorker(runtime)

    await worker.tick()

    assert runtime.operations._executor.execute_attempt.await_count == 1
    attempt_ids = [call.args[0] for call in runtime.operations._executor.execute_attempt.await_args_list]
    claim_tokens = [call.args[1] for call in runtime.operations._executor.execute_attempt.await_args_list]
    assert attempt_ids == ["attempt-op-created-ready-i0"]
    assert claim_tokens == ["t1"]


@pytest.mark.asyncio
async def test_worker_skips_operation_if_already_processed_by_dedup(monkeypatch):
    monkeypatch.setattr("core.operations.worker.time.time", lambda: 1000.0)

    class _Storage:
        def __init__(self):
            self._data: dict[tuple[str, str], object] = {}

        async def get(self, namespace: str, key: str):
            return self._data.get((namespace, key))

        async def set(self, namespace: str, key: str, value: object):
            self._data[(namespace, key)] = value

        async def delete(self, namespace: str, key: str):
            self._data.pop((namespace, key), None)
            return True

    runtime = Mock()
    runtime.storage = _Storage()

    operation = Operation(
        operation_id="op-processed",
        op_type="test.processed",
        params={},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
    )

    runtime.operations = Mock()
    runtime.operations._storage = Mock()
    runtime.operations._storage.ensure_attempt_created = AsyncMock()
    runtime.operations._storage.try_claim_attempt = AsyncMock(return_value=(True, "t1"))
    runtime.operations._storage.persist = AsyncMock()
    runtime.operations._executor = Mock()
    runtime.operations._executor.execute_attempt = AsyncMock()

    ensure_runtime_execution_contract(runtime)

    # Mark operation as processed before execution.
    dedup = DedupLayer(runtime.storage)
    await dedup.mark_operation_processed(operation.operation_id)

    worker = OperationWorker(runtime)
    result = await worker.execute_operation_now(operation)

    assert result.operation_id == "op-processed"
    assert runtime.operations._executor.execute_attempt.await_count == 0


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
    runtime.plugins.integrity_checker.check_runtime_integrity = Mock(return_value=[])

    await runtime.start()
    await asyncio.sleep(0)

    assert runtime.worker is not None
    assert runtime.worker.running is True
    assert runtime._worker_task is not None
    assert not runtime._worker_task.done()

    await runtime.stop()
