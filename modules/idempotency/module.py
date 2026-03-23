from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.runtime_module import RuntimeModule
from modules.hooks.system import CompleteOperation, SystemHookResult, register_system_hook


class IdempotencyModule(RuntimeModule):
    @property
    def name(self) -> str:
        return "idempotency"

    async def register(self) -> None:
        register_system_hook("before_execute", self._before_execute)

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
        except Exception:
            return SystemHookResult(allow=True)

        if isinstance(cached, dict):
            return SystemHookResult(
                allow=False,
                actions=[CompleteOperation(result=cached)],
                reason="idempotent_replay",
                context_patch={"idempotency_cache_hit": True},
            )

        return SystemHookResult(allow=True)