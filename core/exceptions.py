"""
Core exceptions package - unified exception types for consistent error handling.

Provides:
- CoreError: base exception for all core errors
- HTTP-related: BadRequestError, UnauthorizedError, ForbiddenError, NotFoundError
- Storage: StorageSecurityError, StorageConfigurationError, NamespaceViolationError
"""

from __future__ import annotations

from core.adapters.storage_errors import (
    NamespaceViolationError,
    StorageConfigurationError,
    StorageCorruptionError,
    StorageRollbackDetected,
    StorageSecurityError,
    StorageTamperDetected,
)


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

__all__ = [
    "CoreError",
    "BadRequestError",
    "UnauthorizedError",
    "ForbiddenError",
    "NotFoundError",
    "StorageSecurityError",
    "StorageConfigurationError",
    "NamespaceViolationError",
    "StorageCorruptionError",
    "StorageRollbackDetected",
    "StorageTamperDetected",
]
