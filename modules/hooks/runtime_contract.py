from __future__ import annotations

from typing import Any, Iterable, Mapping

from core.operations.runtime_contract import HookDecision
from modules.operation_source.module import DefaultOperationSource

from .action_resolver import resolve_actions
from .actions import dispatch_action
from .system import dispatch_system_hooks, merge_system_hook_results


class ModulesHooksAdapter:
    async def run(self, hook_name: str, ctx: Mapping[str, Any]) -> HookDecision:
        results = await dispatch_system_hooks(hook_name, dict(ctx))
        decision = merge_system_hook_results(results)

        merged_ctx = dict(ctx)
        context_patch = getattr(decision, "context_patch", None)
        if context_patch:
            merged_ctx.update(context_patch)

        return HookDecision(
            context=merged_ctx,
            allow=bool(getattr(decision, "allow", True)),
            actions=tuple(getattr(decision, "actions", ()) or ()),
        )


class ModulesActionDispatcherAdapter:
    async def dispatch(self, action: Any, ctx: Mapping[str, Any]) -> None:
        await dispatch_action(action, ctx)


class ModulesActionResolverAdapter:
    def resolve(self, actions: Iterable[Any]) -> list[Any]:
        return list(resolve_actions(actions))


def ensure_runtime_execution_contract(runtime: Any) -> None:
    runtime_dict = getattr(runtime, "__dict__", {})

    if runtime_dict.get("hooks") is None:
        runtime.hooks = ModulesHooksAdapter()
    if runtime_dict.get("action_dispatcher") is None:
        runtime.action_dispatcher = ModulesActionDispatcherAdapter()
    if runtime_dict.get("action_resolver") is None:
        runtime.action_resolver = ModulesActionResolverAdapter()
    if runtime_dict.get("operation_source") is None:
        runtime.operation_source = DefaultOperationSource(runtime.operations)
