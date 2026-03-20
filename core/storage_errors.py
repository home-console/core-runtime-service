"""Compatibility exports for storage errors.

Canonical implementations live in modules.storage.errors.
"""

from modules.storage.errors import (
    NamespaceViolationError,
    StorageConfigurationError,
    StorageSecurityError,
)

__all__ = [
    "StorageSecurityError",
    "StorageConfigurationError",
    "NamespaceViolationError",
]
