from __future__ import annotations

import inspect
import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, TypeAlias, cast

from .context_merge import ContextPatch, resolve_context_patches

SystemHookContext: TypeAlias = Mapping[str, Any]
SystemHookHandler: TypeAlias = Callable[[SystemHookContext], Any]

_logger = logging.getLogger(__name__)
_hook_registry: dict[str, list[SystemHookHandler]] = {}
_hook_registry_lock = threading.RLock()


@dataclass(frozen=True)
class ExecutionAction:
    pass


@dataclass(frozen=True)
class ScheduleRetry(ExecutionAction):
    at: float


@dataclass(frozen=True)
class CancelOperation(ExecutionAction):
    reason: str


@dataclass(frozen=True)
class CompleteOperation(ExecutionAction):
    result: Any


@dataclass(frozen=True)
class SystemHookResult:
    allow: bool = True
    actions: tuple[ExecutionAction, ...] = ()
    context_patch: dict[str, Any] | ContextPatch | None = None
    reason: str | None = None


@dataclass(frozen=True)
class SystemHookDecision:
    allow: bool = True
    actions: tuple[ExecutionAction, ...] = ()
    context_patch: dict[str, Any] | None = None
    reasons: tuple[str, ...] = ()


def _normalize_action(action: Any) -> ExecutionAction:
    if isinstance(action, ExecutionAction):
        return action
    if isinstance(action, dict):
        action_data = cast(dict[str, Any], action)
        action_type = "".join(
            ch
            for ch in str(action_data.get("type", "")).strip().lower()
            if ch.isalnum()
        )
        if action_type == "scheduleretry":
            return ScheduleRetry(at=float(action_data["at"]))
        if action_type == "canceloperation":
            return CancelOperation(reason=str(action_data["reason"]))
        if action_type == "completeoperation":
            return CompleteOperation(result=action_data.get("result"))
    raise TypeError("system hook actions must be ExecutionAction instances")


def register_system_hook(hook_name: str, handler: SystemHookHandler) -> None:
    if not hook_name:
        raise ValueError("hook_name must be a non-empty string")
    if not callable(handler):
        raise TypeError("handler must be callable")

    with _hook_registry_lock:
        _hook_registry.setdefault(hook_name, []).append(handler)


def get_system_hooks(hook_name: str) -> list[SystemHookHandler]:
    with _hook_registry_lock:
        return list(_hook_registry.get(hook_name, []))


def clear_system_hooks() -> None:
    with _hook_registry_lock:
        _hook_registry.clear()


def _normalize_hook_result(result: Any) -> SystemHookResult | None:
    if result is None:
        return None
    if isinstance(result, SystemHookResult):
        return result
    if isinstance(result, dict):
        result_data = cast(dict[str, Any], result)
        actions = cast(list[Any], result_data.get("actions") or [])
        return SystemHookResult(
            allow=bool(result_data.get("allow", True)),
            actions=tuple(_normalize_action(action) for action in actions),
            context_patch=cast(dict[str, Any] | ContextPatch | None, result_data.get("context_patch")),
            reason=cast(str | None, result_data.get("reason")),
        )
    raise TypeError("system hooks must return SystemHookResult, dict, or None")


class HookDispatcher:
    async def dispatch_system_hooks(
        self, hook_name: str, ctx: SystemHookContext
    ) -> list[SystemHookResult]:
        handlers = get_system_hooks(hook_name)
        results: list[SystemHookResult] = []

        for handler in handlers:
            try:
                outcome = handler(ctx)
                if inspect.isawaitable(outcome):
                    outcome = await outcome
                normalized = _normalize_hook_result(outcome)
                if normalized is not None:
                    results.append(normalized)
            except Exception:
                _logger.exception("system hook failed", extra={"hook_name": hook_name})
                continue

        return results


_default_dispatcher = HookDispatcher()


async def dispatch_system_hooks(
    hook_name: str, ctx: SystemHookContext
) -> list[SystemHookResult]:
    return await _default_dispatcher.dispatch_system_hooks(hook_name, ctx)


def merge_system_hook_results(
    results: list[SystemHookResult],
) -> SystemHookDecision:
    allow = True
    actions: list[ExecutionAction] = []
    context_patches: list[dict[str, Any] | ContextPatch] = []
    reasons: list[str] = []

    for result in results:
        allow = allow and result.allow

        if result.actions:
            actions.extend(result.actions)

        if result.context_patch:
            context_patches.append(result.context_patch)

        if result.reason:
            reasons.append(result.reason)

    return SystemHookDecision(
        allow=allow,
        actions=tuple(actions),
        context_patch=resolve_context_patches(context_patches) or None,
        reasons=tuple(reasons),
    )
