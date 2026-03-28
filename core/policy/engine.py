"""Core policy primitives (policy-agnostic by design)."""

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Iterable, List, Optional

from core.auth_contextvars import get_current_auth_context


class Policy(ABC):
    @abstractmethod
    def enforce(self, ctx: Any, obj: Any) -> None:
        pass

    @abstractmethod
    def filter(self, ctx: Any, items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        pass


class PolicyEngine:
    def __init__(
        self,
        context_provider: Optional[Callable[[], Any]] = None,
    ):
        self._policies: Dict[str, Policy] = {}
        self._context_provider: Callable[[], Any] = (
            context_provider if context_provider is not None else get_current_auth_context
        )

    def register_policy(self, resource_type: str, policy: Policy) -> None:
        self._policies[resource_type] = policy

    def get_policy(self, resource_type: str) -> Optional[Policy]:
        return self._policies.get(resource_type)

    def enforce_policy(self, ctx: Any, resource_type: str, obj: Any) -> None:
        policy = self.get_policy(resource_type)
        if policy is None:
            return

        policy.enforce(ctx, obj)

    def filter_with_policy(
        self,
        ctx: Any,
        resource_type: str,
        items: Iterable[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        policy = self.get_policy(resource_type)
        if policy is None:
            return list(items)

        return policy.filter(ctx, items)

    def enforce_admin(self, ctx: Any) -> None:
        # Core is policy-agnostic. Admin checks belong to modules.
        return None

    def is_privileged(self, ctx: Any) -> bool:
        # Core is policy-agnostic. Privilege interpretation belongs to modules.
        return False

    def current_context(self) -> Any:
        return self._context_provider()


_global_policy_engine: Optional[PolicyEngine] = None


def get_policy_engine() -> PolicyEngine:
    global _global_policy_engine
    if _global_policy_engine is None:
        _global_policy_engine = PolicyEngine()
    return _global_policy_engine


def set_policy_engine(engine: PolicyEngine) -> None:
    global _global_policy_engine
    _global_policy_engine = engine
