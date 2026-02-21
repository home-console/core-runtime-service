"""
Core ContextVar for the current auth/request context.

Важно:
- Core слой не должен импортировать modules/api напрямую.
- Контекст может быть любым объектом, у которого есть user_id/scopes/is_admin.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Optional, Dict


_current_auth_context: ContextVar[Optional[Any]] = ContextVar("current_auth_context", default=None)

# Cookies that need to be set by the HTTP layer
# Default to empty dict if not set
_response_cookies: ContextVar[Dict[str, Dict[str, Any]]] = ContextVar("response_cookies", default=None)


def set_current_auth_context(ctx: Optional[Any]) -> None:
    _current_auth_context.set(ctx)


def get_current_auth_context() -> Optional[Any]:
    return _current_auth_context.get()


def set_response_cookie(
    key: str,
    value: str,
    max_age: Optional[int] = None,
    httponly: bool = False,
    secure: bool = False,
    samesite: str = "Lax",
    path: str = "/",
) -> None:
    """
    Register a cookie to be set by the HTTP layer.
    
    Services call this to request cookies be set.
    route_binding reads these from contextvars and sets them via response.set_cookie().
    """
    cookies = _response_cookies.get()
    if cookies is None:
        cookies = {}
    cookies[key] = {
        "value": value,
        "max_age": max_age,
        "httponly": httponly,
        "secure": secure,
        "samesite": samesite,
        "path": path,
    }
    _response_cookies.set(cookies)


def get_response_cookies() -> Dict[str, Dict[str, Any]]:
    """Get cookies that need to be set by HTTP layer."""
    cookies = _response_cookies.get()
    if cookies is None:
        return {}
    return cookies.copy()


def clear_response_cookies(key: Optional[str] = None) -> None:
    """Clear cookies.
    
    If key is provided, clear that specific cookie by setting max_age to 0.
    Otherwise, clear all cookies (usually called after they've been set by HTTP layer).
    """
    if key:
        # Mark specific cookie for deletion
        cookies = _response_cookies.get()
        if cookies is None:
            cookies = {}
        cookies[key] = {
            "value": "",
            "max_age": 0,
            "httponly": False,
            "secure": False,
            "samesite": "Lax",
            "path": "/",
        }
        _response_cookies.set(cookies)
    else:
        # Clear all cookies
        _response_cookies.set({})
