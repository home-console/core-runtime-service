"""
Core exceptions package - unified exception types for consistent error handling.

Provides:
- CoreError: base exception for all core errors
- HTTP-related: BadRequestError, UnauthorizedError, ForbiddenError, NotFoundError
- Storage: StorageSecurityError, StorageConfigurationError, NamespaceViolationError
"""

# Import from legacy files for backward compatibility
from core.exceptions.errors import (
    CoreError,
    BadRequestError,
    UnauthorizedError,
    ForbiddenError,
    NotFoundError,
)
from core.storage_errors import (
    StorageSecurityError,
    StorageConfigurationError,
    NamespaceViolationError,
)

__all__ = [
    "CoreError",
    "BadRequestError",
    "UnauthorizedError",
    "ForbiddenError",
    "NotFoundError",
    "StorageSecurityError",
    "StorageConfigurationError",
    "NamespaceViolationError",
]
