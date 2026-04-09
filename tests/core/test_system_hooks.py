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
from modules.hooks.context_merge import ContextPatch, resolve_context_patches
from modules.hooks.runtime_contract import ensure_runtime_execution_contract


@pytest.fixture(autouse=True)
def clear_hooks_registry():
    clear_system_hooks()
    yield
    clear_system_hooks()


def test_resolve_context_patches_last_wins_conflict():
    resolved = resolve_context_patches(
        [
            {"timeout": 10},
            {"timeout": 30},
        ]
    )

    assert resolved == {"timeout": 30}


def test_resolve_context_patches_merges_nested_dicts():
    resolved = resolve_context_patches(
        [
            {"timeout": 10, "retry": {"count": 1, "policy": {"base": 2}}},
            {"retry": {"policy": {"max": 8}, "jitter": True}},
        ]
    )

    assert resolved == {
        "timeout": 10,
        "retry": {"count": 1, "policy": {"base": 2, "max": 8}, "jitter": True},
    }


def test_resolve_context_patches_deny_override_preserves_value():
    resolved = resolve_context_patches(
        [
            ContextPatch(data={"timeout": 10}, deny_override=True),
            {"timeout": 30, "mode": "fast"},
        ],
        rule="deny_override",
    )

    assert resolved == {"timeout": 10, "mode": "fast"}


def test_merge_system_hook_results_uses_context_patch_resolution():
    decision = merge_system_hook_results(
        [
            SystemHookResult(context_patch={"timeout": 10, "retry": {"count": 1}}),
            SystemHookResult(context_patch={"timeout": 30, "retry": {"policy": "linear"}}),
        ]
    )

    assert decision.context_patch == {
        "timeout": 30,
        "retry": {"count": 1, "policy": "linear"},
    }


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
            actions=(ScheduleRetry(at=1005.0),),
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
            actions=(ScheduleRetry(at=1030.0),),
        ),
    )
    ensure_runtime_execution_contract(runtime)

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
    ensure_runtime_execution_contract(runtime)

    operation = Operation(
        operation_id="op-block",
        op_type="test.blocked",
        params={},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
    )

    worker = OperationWorker(runtime)
    result = await worker.execute_operation_now(operation)

    assert result.status == OperationStatus.CREATED
    assert result.error is None
    assert result.finished_at is None
    runtime.operations._executor.execute_attempt.assert_not_called()
    runtime.operations._storage.persist_attempt.assert_awaited_once()
