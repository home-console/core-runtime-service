from __future__ import annotations

import json
from typing import Iterable

from .system import CancelOperation, CompleteOperation, ExecutionAction, ScheduleRetry


PRIORITY = {
    "CompleteOperation": 100,
    "CancelOperation": 90,
    "ScheduleRetry": 50,
}


def _priority(action: ExecutionAction) -> int:
    return PRIORITY.get(type(action).__name__, 0)


def _stable_value(action: ExecutionAction) -> str:
    if isinstance(action, CompleteOperation):
        payload = action.result
    elif isinstance(action, CancelOperation):
        payload = action.reason
    elif isinstance(action, ScheduleRetry):
        payload = action.at
    else:
        payload = action
    try:
        return json.dumps(payload, sort_keys=True, default=str)
    except Exception:
        return repr(payload)


def _winner(actions: Iterable[ExecutionAction]) -> ExecutionAction:
    return max(actions, key=lambda action: (_priority(action), _stable_value(action)))


def resolve_actions(actions: Iterable[ExecutionAction]) -> list[ExecutionAction]:
    action_list = list(actions)
    if not action_list:
        return []

    complete_actions = [action for action in action_list if isinstance(action, CompleteOperation)]
    if complete_actions:
        return [_winner(complete_actions)]

    cancel_actions = [action for action in action_list if isinstance(action, CancelOperation)]
    if cancel_actions:
        return [_winner(cancel_actions)]

    retry_actions = [action for action in action_list if isinstance(action, ScheduleRetry)]
    if retry_actions:
        merged_retry = ScheduleRetry(at=max(action.at for action in retry_actions))
        passthrough = [action for action in action_list if not isinstance(action, ScheduleRetry)]
        return [*passthrough, merged_retry] if passthrough else [merged_retry]

    return action_list