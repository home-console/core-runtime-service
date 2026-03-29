"""Storage integrity exceptions shared with core primitives."""

from core.storage_errors import (
    StorageCorruptionError,
    StorageRollbackDetected,
    StorageTamperDetected,
)

__all__ = [
    "StorageCorruptionError",
    "StorageRollbackDetected",
    "StorageTamperDetected",
]
