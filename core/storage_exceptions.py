"""Compatibility exports for storage exceptions.

Canonical implementations live in modules.storage.exceptions.
"""

from modules.storage.exceptions import (
    StorageCorruptionError,
    StorageRollbackDetected,
    StorageTamperDetected,
)

__all__ = [
    "StorageCorruptionError",
    "StorageRollbackDetected",
    "StorageTamperDetected",
]
