"""
ACL facade over PolicyEngine.

Canonical ACL helpers for policy checks and context access.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from core.policy import get_policy_engine


def is_privileged(ctx: Any) -> bool:
    """Check whether context has privileged access."""
    policy_engine = get_policy_engine()
    return policy_engine.is_privileged(ctx)


def enforce_admin(ctx: Any) -> None:
    """Require admin privileges for the provided context."""
    policy_engine = get_policy_engine()
    policy_engine.enforce_admin(ctx)


def enforce_policy(ctx: Any, resource: str, obj: Any) -> None:
    """Enforce resource policy for a single object."""
    policy_engine = get_policy_engine()
    policy_engine.enforce_policy(ctx, resource, obj)


def filter_with_policy(ctx: Any, resource: str, items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter items according to resource policy."""
    policy_engine = get_policy_engine()
    return policy_engine.filter_with_policy(ctx, resource, items)


def current_context() -> Any:
    """Return current auth context from contextvars."""
    policy_engine = get_policy_engine()
    return policy_engine.current_context()
