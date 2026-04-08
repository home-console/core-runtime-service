from __future__ import annotations

import time
from typing import Any

from core.operations.models import Operation, OperationStatus
from sdk.operations_events import OPERATION_READY_EVENT_TYPE, build_operation_ready_payload
from core.runtime.runtime_module import RuntimeModule

from modules.hooks.system import (
    ScheduleRetry,
    SystemHookResult,
    register_system_hook,
    unregister_system_hook,
)
from modules.hooks.runtime_contract import ensure_runtime_execution_contract
from modules.retry_policy.policy import can_schedule_retry, compute_next_retry_at, is_retry_due


class RetryPolicyModule(RuntimeModule):
    @property
    def name(self) -> str:
        return "retry_policy"

    def __init__(self, runtime: Any):
        super().__init__(runtime)
        self._hook_bindings: list[tuple[str, Any]] = []

    async def register(self) -> None:
        ensure_runtime_execution_contract(self.runtime)

        register_system_hook("before_claim", self.on_before_claim)
        register_system_hook("on_failure", self.on_failure)
        register_system_hook("after_execute", self.on_after_execute)
        self._hook_bindings.extend(
            [
                ("before_claim", self.on_before_claim),
                ("on_failure", self.on_failure),
                ("after_execute", self.on_after_execute),
            ]
        )

    async def stop(self) -> None:
        for hook_name, handler in self._hook_bindings:
            unregister_system_hook(hook_name, handler)
        self._hook_bindings.clear()

    async def on_before_claim(self, ctx: dict[str, Any]) -> SystemHookResult:
        operation = ctx.get("operation")
        if not isinstance(operation, Operation):
            return SystemHookResult(allow=True)

        if operation.status == OperationStatus.CREATED:
            return SystemHookResult(allow=True)

        if operation.status == OperationStatus.FAILED:
            now = float(ctx.get("now", time.time()))
            if is_retry_due(operation, now=now):
                return SystemHookResult(allow=True)
            return SystemHookResult(allow=False, reason="retry_not_due")

        return SystemHookResult(allow=False, reason="status_not_runnable")

    async def on_failure(self, ctx: dict[str, Any]) -> SystemHookResult:
        operation = ctx.get("operation")
        if not isinstance(operation, Operation):
            return SystemHookResult(allow=True)

        if operation.status != OperationStatus.FAILED:
            return SystemHookResult(allow=True)

        if not can_schedule_retry(operation):
            operation.next_retry_at = None
            return SystemHookResult(allow=True)

        now = time.time()
        next_retry_at = compute_next_retry_at(operation, now=now)
        if next_retry_at <= now:
            event_bus = getattr(self.runtime, "event_bus", None)
            publish = getattr(event_bus, "publish", None)
            if callable(publish):
                await publish(
                    OPERATION_READY_EVENT_TYPE,
                    build_operation_ready_payload(operation.operation_id),
                )
        return SystemHookResult(
            allow=True,
            actions=[ScheduleRetry(at=next_retry_at)],
        )

    async def on_after_execute(self, ctx: dict[str, Any]) -> SystemHookResult:
        operation = ctx.get("operation")
        if not isinstance(operation, Operation):
            return SystemHookResult(allow=True)

        if operation.status != OperationStatus.FAILED:
            operation.next_retry_at = None
        return SystemHookResult(allow=True)
