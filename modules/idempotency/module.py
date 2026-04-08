from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.runtime.runtime_module import RuntimeModule
from modules.hooks.system import (
    CompleteOperation,
    SystemHookResult,
    register_system_hook,
    unregister_system_hook,
)
from modules.hooks.runtime_contract import ensure_runtime_execution_contract
import logging
logger = logging.getLogger(__name__)


class IdempotencyModule(RuntimeModule):
    @property
    def name(self) -> str:
        return "idempotency"

    def __init__(self, runtime: Any):
        super().__init__(runtime)
        self._hook_bindings: list[tuple[str, Any]] = []

    async def register(self) -> None:
        ensure_runtime_execution_contract(self.runtime)

        register_system_hook("before_execute", self._before_execute)
        register_system_hook("after_execute", self._after_execute)
        self._hook_bindings.extend(
            [
                ("before_execute", self._before_execute),
                ("after_execute", self._after_execute),
            ]
        )

    async def stop(self) -> None:
        for hook_name, handler in self._hook_bindings:
            unregister_system_hook(hook_name, handler)
        self._hook_bindings.clear()

    async def _before_execute(self, ctx: Mapping[str, Any]) -> SystemHookResult:
        execution_token = (
            ctx.get("execution_token")
            or getattr(ctx.get("attempt"), "execution_token", None)
            or ctx.get("claim_token")
        )
        if not execution_token:
            return SystemHookResult(allow=True)

        storage = getattr(self.runtime, "storage", None)
        if storage is None:
            return SystemHookResult(allow=True)

        try:
            cached = await storage.get("operation_results", execution_token)
        except Exception as e:
            logger.warning("module._before_execute: failed: %s", e, exc_info=True)
            return SystemHookResult(allow=True)

        if isinstance(cached, dict):
            return SystemHookResult(
                allow=False,
                actions=[CompleteOperation(result=cached)],
                reason="idempotent_replay",
                context_patch={"idempotency_cache_hit": True},
            )

        return SystemHookResult(allow=True)

    async def _after_execute(self, ctx: Mapping[str, Any]) -> SystemHookResult:
        operation = ctx.get("operation") or ctx.get("result")
        if operation is None:
            return SystemHookResult(allow=True)

        execution_token = (
            ctx.get("execution_token")
            or getattr(ctx.get("attempt"), "execution_token", None)
            or ctx.get("claim_token")
        )
        if not execution_token:
            return SystemHookResult(allow=True)

        storage = getattr(self.runtime, "storage", None)
        if storage is None:
            return SystemHookResult(allow=True)

        status_obj = getattr(operation, "status", None)
        error_obj = getattr(operation, "error", None)
        outcome = {
            "status": getattr(status_obj, "value", str(status_obj)),
            "result": getattr(operation, "result", None),
            "error": error_obj.to_dict() if hasattr(error_obj, "to_dict") else None,
            "finished_at": getattr(operation, "finished_at", None),
        }
        try:
            await storage.set("operation_results", execution_token, outcome)
        except Exception:
            logger.warning("Unhandled exception", exc_info=True)
        return SystemHookResult(allow=True)
