from __future__ import annotations

import inspect
import threading
from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

from core.operations.models import (
    Attempt,
    AttemptStatus,
    Operation,
    OperationError,
    OperationStatus,
)

from .system import CancelOperation, CompleteOperation, ExecutionAction, ScheduleRetry
import logging
logger = logging.getLogger(__name__)


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
            logger.debug("actions.dispatch_action: error processing item (skipping)", exc_info=True)
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


class CompleteOperationActionHandler(ActionHandler):
    async def handle(self, action: ExecutionAction, ctx: ActionContext) -> None:
        if not isinstance(action, CompleteOperation):
            return

        operation = ctx.get("operation")
        if not isinstance(operation, Operation):
            return

        payload = action.result
        finished_at = ctx.get("now")

        if isinstance(payload, dict):
            status_value = payload.get("status", OperationStatus.COMPLETED.value)
            try:
                operation.status = OperationStatus(str(status_value))
            except Exception:
                logger.debug("actions.handle: error (using fallback value)", exc_info=True)
                operation.status = OperationStatus.COMPLETED
            operation.result = payload.get("result")

            error_payload = payload.get("error")
            if operation.status == OperationStatus.COMPLETED:
                operation.error = None
            elif isinstance(error_payload, dict):
                operation.error = OperationError(
                    code=str(error_payload.get("code", "execution_error")),
                    message=str(error_payload.get("message", "Execution failed")),
                    details=error_payload.get("details"),
                )
            else:
                operation.error = OperationError(
                    code="execution_error",
                    message="Execution failed",
                )

            finished_at = payload.get("finished_at") or finished_at
        else:
            operation.status = OperationStatus.COMPLETED
            operation.result = payload
            operation.error = None

        operation.finished_at = finished_at

        attempt = ctx.get("attempt")
        if isinstance(attempt, Attempt):
            if operation.status == OperationStatus.COMPLETED:
                attempt.status = AttemptStatus.COMPLETED
                attempt.error = None
            elif operation.status == OperationStatus.CANCELLED:
                attempt.status = AttemptStatus.CANCELLED
                attempt.error = operation.error.to_dict() if operation.error else None
            else:
                attempt.status = AttemptStatus.FAILED
                attempt.error = operation.error.to_dict() if operation.error else None
            attempt.finished_at = finished_at


register_action_handler("ScheduleRetry", ScheduleRetryActionHandler())
register_action_handler("CancelOperation", CancelOperationActionHandler())
register_action_handler("CompleteOperation", CompleteOperationActionHandler())