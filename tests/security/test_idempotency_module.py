from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from core.operations.models import (
    Attempt,
    AttemptStatus,
    Operation,
    OperationInitiator,
    OperationInitiatorKind,
    OperationStatus,
)
from core.operations.worker import OperationWorker
from modules.hooks.system import CompleteOperation, clear_system_hooks, dispatch_system_hooks, merge_system_hook_results
from modules.idempotency.module import IdempotencyModule


@pytest.fixture(autouse=True)
def clear_hooks_registry():
    clear_system_hooks()
    yield
    clear_system_hooks()


@pytest.mark.asyncio
async def test_idempotency_module_emits_complete_operation_action():
    runtime = SimpleNamespace(
        storage=Mock(),
        service_registry=Mock(),
        http=Mock(),
        capability_registry=Mock(),
        operations=Mock(),
    )
    cached = {
        "status": "completed",
        "result": {"value": 42},
        "error": None,
        "finished_at": 1001.0,
    }
    runtime.storage.get = AsyncMock(return_value=cached)

    module = IdempotencyModule(runtime)
    await module.register()

    attempt = Attempt(
        attempt_id="attempt-1",
        operation_id="op-1",
        attempt_index=0,
        status=AttemptStatus.CLAIMED,
        execution_token="exec-1",
    )

    results = await dispatch_system_hooks(
        "before_execute",
        {
            "operation": Operation(
                operation_id="op-1",
                op_type="test.replay",
                params={},
                initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
            ),
            "attempt": attempt,
            "execution_token": "exec-1",
        },
    )
    decision = merge_system_hook_results(results)

    assert decision.allow is False
    assert len(decision.actions) == 1
    assert isinstance(decision.actions[0], CompleteOperation)
    assert decision.actions[0].result == cached


@pytest.mark.asyncio
async def test_worker_short_circuits_on_idempotent_replay(monkeypatch):
    monkeypatch.setattr("core.operations.worker.time.time", lambda: 1000.0)

    runtime = Mock()
    runtime.service_registry = Mock()
    runtime.http = Mock()
    runtime.capability_registry = Mock()
    runtime.operations = Mock()
    runtime.operations._storage = Mock()
    runtime.operations._storage.ensure_attempt_created = AsyncMock()
    runtime.operations._storage.try_claim_attempt = AsyncMock(return_value=(True, "claim-1"))
    runtime.operations._storage.get_attempt = AsyncMock(
        return_value=Attempt(
            attempt_id="attempt-op-1-i0",
            operation_id="op-1",
            attempt_index=0,
            status=AttemptStatus.CLAIMED,
            claim_token="claim-1",
            execution_token="claim-1",
            worker_id="worker-1",
        )
    )
    runtime.operations._storage.persist_attempt = AsyncMock()
    runtime.operations._storage.persist = AsyncMock()
    runtime.operations._executor = Mock()
    runtime.operations._executor.execute_attempt = AsyncMock()

    cached = {
        "status": "completed",
        "result": {"value": 7},
        "error": None,
        "finished_at": 1000.0,
    }

    async def _storage_get(namespace, key):
        if namespace == "operation_results":
            return cached
        if namespace == "operations":
            return None
        return None

    runtime.storage = Mock()
    runtime.storage.get = AsyncMock(side_effect=_storage_get)

    module = IdempotencyModule(runtime)
    await module.register()

    worker = OperationWorker(runtime)
    operation = Operation(
        operation_id="op-1",
        op_type="test.replay",
        params={},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
    )

    result = await worker.execute_operation_now(operation)

    assert result.status == OperationStatus.COMPLETED
    assert result.result == {"value": 7}
    runtime.operations._executor.execute_attempt.assert_not_called()