from __future__ import annotations

import time
from typing import Any

from core.operations.models import RETRYABLE_ERRORS, Operation, OperationStatus
from core.runtime_module import RuntimeModule

from modules.hooks.system import ScheduleRetry, SystemHookResult, register_system_hook


class RetryPolicyModule(RuntimeModule):
    @property
    def name(self) -> str:
        return "retry_policy"

    async def register(self) -> None:
        register_system_hook("on_failure", self.on_failure)

    async def on_failure(self, ctx: dict[str, Any]) -> SystemHookResult:
        operation = ctx.get("operation")
        if not isinstance(operation, Operation):
            return SystemHookResult(allow=True)

        error = operation.error
        if (
            operation.status != OperationStatus.FAILED
            or error is None
            or error.code not in RETRYABLE_ERRORS
            or operation.retry_count >= operation.max_retries
        ):
            return SystemHookResult(allow=True)

        next_retry_at = time.time() + float(2**operation.retry_count)
        return SystemHookResult(
            allow=True,
            actions=[ScheduleRetry(at=next_retry_at)],
        )
