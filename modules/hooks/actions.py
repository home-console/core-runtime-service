from __future__ import annotations

import inspect
import threading
from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

from core.operations.models import Operation, OperationStatus

from .system import CancelOperation, ExecutionAction, ScheduleRetry


ActionContext = Mapping[str, Any]


class ActionHandler(ABC):
    @abstractmethod
    async def handle(self, action: ExecutionAction, ctx: ActionContext) -> None:
        pass


_action_registry: dict[str, list[ActionHandler]] = {}
_action_registry_lock = threading.RLock()


def register_action_handler(action_type: str, handler: ActionHandler) -> None:
    if not action_type or not isinstance(action_type, str):
        raise ValueError("action_type must be a non-empty string")
    if not isinstance(handler, ActionHandler):
        raise TypeError("handler must be an ActionHandler")

    with _action_registry_lock:
        _action_registry.setdefault(action_type, []).append(handler)


def _action_type(action: ExecutionAction) -> str:
    return type(action).__name__


async def dispatch_action(action: ExecutionAction, ctx: ActionContext) -> None:
    handlers = list(_action_registry.get(_action_type(action), []))
    for handler in handlers:
        try:
            outcome = handler.handle(action, ctx)
            if inspect.isawaitable(outcome):
                await outcome
        except Exception:
            continue


class ScheduleRetryActionHandler(ActionHandler):
    async def handle(self, action: ExecutionAction, ctx: ActionContext) -> None:
        if not isinstance(action, ScheduleRetry):
            return
        operation = ctx.get("operation")
        if not isinstance(operation, Operation):
            return
        operation.next_retry_at = float(action.at)
        operation.retry_count += 1


class CancelOperationActionHandler(ActionHandler):
    async def handle(self, action: ExecutionAction, ctx: ActionContext) -> None:
        if not isinstance(action, CancelOperation):
            return
        operation = ctx.get("operation")
        if not isinstance(operation, Operation):
            return
        operation.status = OperationStatus.CANCELLED
        operation.error = None
        operation.result = None
        operation.cancel_requested = True
        operation.finished_at = ctx.get("now")


register_action_handler("ScheduleRetry", ScheduleRetryActionHandler())
register_action_handler("CancelOperation", CancelOperationActionHandler())