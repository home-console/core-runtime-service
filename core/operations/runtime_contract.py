from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Protocol

from core.operations.models import Operation


@dataclass(frozen=True)
class HookDecision:
    context: dict[str, Any]
    allow: bool = True
    actions: tuple[Any, ...] = ()


class ExecutionHooks(Protocol):
    async def run(self, hook_name: str, ctx: Mapping[str, Any]) -> HookDecision:
        ...


class ActionDispatcher(Protocol):
    async def dispatch(self, action: Any, ctx: Mapping[str, Any]) -> None:
        ...


class ActionResolver(Protocol):
    def resolve(self, actions: Iterable[Any]) -> Iterable[Any]:
        ...


class OperationSource(Protocol):
    async def get_runnable(self) -> list[Operation]:
        ...


class NoopExecutionHooks:
    async def run(self, hook_name: str, ctx: Mapping[str, Any]) -> HookDecision:
        del hook_name
        return HookDecision(context=dict(ctx), allow=True, actions=())


class NoopActionDispatcher:
    async def dispatch(self, action: Any, ctx: Mapping[str, Any]) -> None:
        del action, ctx
        return None


class PassThroughActionResolver:
    def resolve(self, actions: Iterable[Any]) -> list[Any]:
        return list(actions or ())


class NoopOperationSource:
    async def get_runnable(self) -> list[Operation]:
        return []
