"""
Core error types for consistent error handling across modules/plugins.

Почему:
- Доменные сервисы не должны зависеть от FastAPI/HTTPException
- Но нам нужно различать 400/401/403/404 на boundary-слое
- И избегать Information Disclosure (например, 404 вместо 403 на resource access)
"""

from __future__ import annotations


class CoreError(Exception):
    """Base class for typed errors."""


class BadRequestError(CoreError):
    """Client sent invalid request (400)."""


class UnauthorizedError(CoreError):
    """Authentication required/invalid (401)."""


class ForbiddenError(CoreError):
    """Authenticated, but not allowed (403)."""


class NotFoundError(CoreError):
    """Resource not found (404)."""

