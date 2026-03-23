from modules.hooks.action_resolver import resolve_actions
from modules.hooks.system import CancelOperation, CompleteOperation, ScheduleRetry


def test_complete_operation_wins_over_retry():
    actions = [
        ScheduleRetry(at=1005.0),
        CompleteOperation(result={"status": "completed", "result": {"ok": True}}),
    ]

    resolved = resolve_actions(actions)

    assert len(resolved) == 1
    assert isinstance(resolved[0], CompleteOperation)
    assert resolved[0].result == {"status": "completed", "result": {"ok": True}}


def test_cancel_operation_wins_over_retry():
    actions = [
        ScheduleRetry(at=1005.0),
        CancelOperation(reason="policy"),
    ]

    resolved = resolve_actions(actions)

    assert len(resolved) == 1
    assert isinstance(resolved[0], CancelOperation)
    assert resolved[0].reason == "policy"


def test_multiple_retries_merge_to_single_retry():
    actions = [
        ScheduleRetry(at=1005.0),
        ScheduleRetry(at=1010.0),
        ScheduleRetry(at=1007.5),
    ]

    resolved = resolve_actions(actions)

    assert len(resolved) == 1
    assert isinstance(resolved[0], ScheduleRetry)
    assert resolved[0].at == 1010.0