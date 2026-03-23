"""Core storage integrity exceptions."""


class StorageCorruptionError(RuntimeError):
    """Storage corruption detected (invalid JSON, hash mismatch, etc.)."""

    pass


class StorageRollbackDetected(RuntimeError):
    """Rollback attack detected via epoch regression."""

    pass


class StorageTamperDetected(RuntimeError):
    """Protected data was modified outside expected secure flow."""

    pass


__all__ = ["StorageCorruptionError", "StorageRollbackDetected", "StorageTamperDetected"]
