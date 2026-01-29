"""
Core ContextVar for the current auth/request context.

Важно:
- Core слой не должен импортировать modules/api напрямую.
- Контекст может быть любым объектом, у которого есть user_id/scopes/is_admin.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Optional


_current_auth_context: ContextVar[Optional[Any]] = ContextVar("current_auth_context", default=None)


def set_current_auth_context(ctx: Optional[Any]) -> None:
    _current_auth_context.set(ctx)


def get_current_auth_context() -> Optional[Any]:
    return _current_auth_context.get()

