"""
ContextVars for passing RequestContext across service calls within the same request.

Реальная реализация живёт в core (`core/auth_contextvars.py`), чтобы ядро не зависело от modules/api.
Этот модуль — тонкая обёртка для обратной совместимости.
"""

from __future__ import annotations

from typing import Optional, Any

from core.auth_contextvars import get_current_auth_context, set_current_auth_context

from .context import RequestContext


def set_current_request_context(ctx: Optional[RequestContext]) -> None:
    set_current_auth_context(ctx)


def get_current_request_context() -> Optional[Any]:
    return get_current_auth_context()

