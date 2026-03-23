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
from modules.hooks.system import clear_system_hooks, get_system_hooks
from modules.retry_policy import RetryPolicyModule


@pytest.fixture(autouse=True)
def clear_hooks_registry():
    clear_system_hooks()
    yield
    clear_system_hooks()


@pytest.mark.asyncio
async def test_retry_policy_module_registers_on_failure_hook_and_schedules_retry(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("modules.retry_policy.module.time.time", lambda: 1000.0)

    runtime = Mock()
    runtime.operations = Mock()
    runtime.operations._storage = Mock()
    runtime.operations._storage.ensure_attempt_created = AsyncMock()
    runtime.operations._storage.try_claim_attempt = AsyncMock(return_value=(True, "claim-token"))
    runtime.operations._storage.persist = AsyncMock()
    runtime.operations._storage.get_attempt = AsyncMock()
    runtime.operations._executor = Mock()

    module = RetryPolicyModule(runtime)
    await module.register()

    assert len(get_system_hooks("on_failure")) == 1

    operation = Operation(
        operation_id="op-retry-policy",
        op_type="test.retryable",
        params={},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
        max_retries=3,
    )

    failed_result = Operation(
        operation_id="op-retry-policy",
        op_type="test.retryable",
        params={},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
        max_retries=3,
    )
    failed_result.status = OperationStatus.FAILED
    failed_result.error = OperationError(code="timeout", message="temporary failure")
    runtime.operations._executor.execute_attempt = AsyncMock(return_value=failed_result)

    worker = OperationWorker(runtime)
    result = await worker.execute_operation_now(operation)

    assert result.status == OperationStatus.FAILED
    assert result.retry_count == 1
    assert result.next_retry_at == 1001.0