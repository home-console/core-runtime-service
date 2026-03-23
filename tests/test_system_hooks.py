from collections.abc import Mapping
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from core.operations.models import (
    Attempt,
    AttemptStatus,
    Operation,
    OperationError,
    OperationInitiator,
    OperationInitiatorKind,
    OperationStatus,
)
from core.operations.worker import OperationWorker
from modules.hooks.system import (
    HookDispatcher,
    ScheduleRetry,
    SystemHookResult,
    clear_system_hooks,
    get_system_hooks,
    merge_system_hook_results,
    register_system_hook,
)


@pytest.fixture(autouse=True)
def clear_hooks_registry():
    clear_system_hooks()
    yield
    clear_system_hooks()


@pytest.mark.asyncio
async def test_hook_dispatcher_collects_results_and_survives_failures():
    async def first_handler(ctx: Mapping[str, Any]) -> SystemHookResult:
        assert ctx["operation_id"] == "op-1"
        return SystemHookResult(
            allow=True,
            context_patch={"first": True},
            reason="first",
        )

    def failing_handler(ctx: Mapping[str, Any]) -> None:
        raise RuntimeError("boom")

    def third_handler(ctx: Mapping[str, Any]) -> SystemHookResult:
        return SystemHookResult(
            allow=False,
            actions=[ScheduleRetry(at=1005.0)],
            context_patch={"third": True},
            reason="third",
        )

    register_system_hook("before_claim", first_handler)
    register_system_hook("before_claim", failing_handler)
    register_system_hook("before_claim", third_handler)

    assert len(get_system_hooks("before_claim")) == 3

    dispatcher = HookDispatcher()
    results = await dispatcher.dispatch_system_hooks(
        "before_claim", {"operation_id": "op-1"}
    )
    decision = merge_system_hook_results(results)

    assert len(results) == 2
    assert decision.allow is False
    assert decision.actions == (ScheduleRetry(at=1005.0),)
    assert decision.context_patch == {"first": True, "third": True}
    assert decision.reasons == ("first", "third")


@pytest.mark.asyncio
async def test_worker_applies_retry_override_from_failure_hook(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("core.operations.worker.time.time", lambda: 1000.0)

    runtime = Mock()
    runtime.operations = Mock()
    runtime.operations._storage = Mock()
    runtime.operations._storage.ensure_attempt_created = AsyncMock()
    runtime.operations._storage.try_claim_attempt = AsyncMock(
        return_value=(True, "claim-token")
    )
    runtime.operations._storage.persist = AsyncMock()
    runtime.operations._storage.get_attempt = AsyncMock()
    runtime.operations._executor = Mock()

    operation = Operation(
        operation_id="op-retry-hook",
        op_type="test.retryable",
        params={},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
        max_retries=3,
    )

    failed_result = Operation(
        operation_id="op-retry-hook",
        op_type="test.retryable",
        params={},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
        max_retries=3,
    )
    failed_result.status = OperationStatus.FAILED
    failed_result.error = OperationError(code="timeout", message="temporary failure")

    runtime.operations._executor.execute_attempt = AsyncMock(return_value=failed_result)
    runtime.operations._storage.get_attempt.return_value = Attempt(
        attempt_id="attempt-op-retry-hook-i0",
        operation_id="op-retry-hook",
        attempt_index=0,
        status=AttemptStatus.CLAIMED,
        claim_token="claim-token",
        execution_token="claim-token",
        worker_id="worker-1",
    )

    register_system_hook(
        "on_failure",
        lambda ctx: SystemHookResult(
            allow=True,
            actions=[ScheduleRetry(at=1030.0)],
        ),
    )

    worker = OperationWorker(runtime)
    result = await worker.execute_operation_now(operation)

    assert result.status == OperationStatus.FAILED
    assert result.error is not None
    assert result.error.code == "timeout"
    assert result.retry_count == 1
    assert result.next_retry_at == 1030.0
    runtime.operations._executor.execute_attempt.assert_awaited_once()


@pytest.mark.asyncio
async def test_before_execute_hook_can_block_execution(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("core.operations.worker.time.time", lambda: 1000.0)

    runtime = Mock()
    runtime.operations = Mock()
    runtime.operations._storage = Mock()
    runtime.operations._storage.ensure_attempt_created = AsyncMock()
    runtime.operations._storage.try_claim_attempt = AsyncMock(
        return_value=(True, "claim-token")
    )
    runtime.operations._storage.persist = AsyncMock()
    runtime.operations._storage.get_attempt = AsyncMock(
        return_value=Attempt(
            attempt_id="attempt-op-block-i0",
            operation_id="op-block",
            attempt_index=0,
            status=AttemptStatus.CLAIMED,
            claim_token="claim-token",
            execution_token="claim-token",
            worker_id="worker-1",
        )
    )
    runtime.operations._storage.persist_attempt = AsyncMock()
    runtime.operations._executor = Mock()
    runtime.operations._executor.execute_attempt = AsyncMock()

    register_system_hook(
        "before_execute",
        lambda ctx: SystemHookResult(allow=False, reason="maintenance window"),
    )

    operation = Operation(
        operation_id="op-block",
        op_type="test.blocked",
        params={},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
    )

    worker = OperationWorker(runtime)
    result = await worker.execute_operation_now(operation)

    assert result.status == OperationStatus.FAILED
    assert result.error is not None
    assert result.error.code == "hook_blocked"
    assert result.finished_at == 1000.0
    runtime.operations._executor.execute_attempt.assert_not_called()
    runtime.operations._storage.persist_attempt.assert_awaited_once()
