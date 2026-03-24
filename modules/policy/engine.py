"""Policy engine moved from core to modules layer."""

from abc import ABC, abstractmethod
from typing import Any, Dict, Iterable, List, Optional

from core.auth_contextvars import get_current_auth_context
from core.exceptions.errors import ForbiddenError, NotFoundError


class Policy(ABC):
    @abstractmethod
    def enforce(self, ctx: Any, obj: Any) -> None:
        pass

    @abstractmethod
    def filter(self, ctx: Any, items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        pass


class DevicePolicy(Policy):
    def enforce(self, ctx: Any, obj: Any) -> None:
        if obj is None:
            raise NotFoundError("device not found")

        if self._is_privileged(ctx):
            return

        user_id = getattr(ctx, "user_id", None) if ctx else None
        if not user_id:
            raise NotFoundError("device not found")

        if isinstance(obj, dict):
            owner_id = obj.get("owner_id")
            if owner_id and owner_id == user_id:
                return
            shared_with = obj.get("shared_with")
            if isinstance(shared_with, list) and user_id in shared_with:
                return

        raise NotFoundError("device not found")

    def filter(self, ctx: Any, items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if ctx is None:
            return list(items)

        result: List[Dict[str, Any]] = []
        for item in items:
            try:
                self.enforce(ctx, item)
                result.append(item)
            except Exception:
                continue
        return result

    def _is_privileged(self, ctx: Any) -> bool:
        if not ctx:
            return False

        from core.system_context import is_system_context

        if is_system_context(ctx):
            return True

        try:
            if getattr(ctx, "is_admin", False):
                return True
            scopes = getattr(ctx, "scopes", set()) or set()
            return ("admin.*" in scopes) or ("*" in scopes)
        except Exception:
            return False


class AdminOnlyPolicy(Policy):
    def enforce(self, ctx: Any, obj: Any) -> None:
        if ctx is None:
            raise ForbiddenError("forbidden: admin operation requires context")

        if self._is_privileged(ctx):
            return

        raise ForbiddenError("forbidden")

    def filter(self, ctx: Any, items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if ctx is None:
            return []

        if self._is_privileged(ctx):
            return list(items)

        return []

    def _is_privileged(self, ctx: Any) -> bool:
        if not ctx:
            return False

        from core.system_context import is_system_context

        if is_system_context(ctx):
            return True

        try:
            if getattr(ctx, "is_admin", False):
                return True
            scopes = getattr(ctx, "scopes", set()) or set()
            return ("admin.*" in scopes) or ("*" in scopes)
        except Exception:
            return False


class PolicyEngine:
    def __init__(self):
        self._policies: Dict[str, Policy] = {}
        self.register_policy("device", DevicePolicy())
        self.register_policy("device_mapping", AdminOnlyPolicy())
        self.register_policy("external_inventory", AdminOnlyPolicy())

    def register_policy(self, resource_type: str, policy: Policy) -> None:
        self._policies[resource_type] = policy

    def get_policy(self, resource_type: str) -> Optional[Policy]:
        return self._policies.get(resource_type)

    def enforce_policy(self, ctx: Any, resource_type: str, obj: Any) -> None:
        if ctx is None:
            return

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
        if ctx is None:
            return list(items)

        policy = self.get_policy(resource_type)
        if policy is None:
            return list(items)

        return policy.filter(ctx, items)

    def enforce_admin(self, ctx: Any) -> None:
        if ctx is None:
            raise ForbiddenError("forbidden: admin operation requires context")

        if self._is_privileged(ctx):
            return

        raise ForbiddenError("forbidden")

    def is_privileged(self, ctx: Any) -> bool:
        return self._is_privileged(ctx)

    def _is_privileged(self, ctx: Any) -> bool:
        if not ctx:
            return False

        from core.system_context import is_system_context

        if is_system_context(ctx):
            return True

        try:
            if getattr(ctx, "is_admin", False):
                return True
            scopes = getattr(ctx, "scopes", set()) or set()
            return ("admin.*" in scopes) or ("*" in scopes)
        except Exception:
            return False

    def current_context(self) -> Any:
        return get_current_auth_context()


_global_policy_engine: Optional[PolicyEngine] = None


def get_policy_engine() -> PolicyEngine:
    global _global_policy_engine
    if _global_policy_engine is None:
        _global_policy_engine = PolicyEngine()
    return _global_policy_engine


def set_policy_engine(engine: PolicyEngine) -> None:
    global _global_policy_engine
    _global_policy_engine = engine
