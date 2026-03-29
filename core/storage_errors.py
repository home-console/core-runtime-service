"""Core storage errors: security, configuration, and integrity exceptions."""


class StorageSecurityError(Exception):
    """Storage security violation."""

    pass


class StorageConfigurationError(Exception):
    """Invalid storage configuration."""

    pass


class NamespaceViolationError(StorageSecurityError):
    """Attempt to write critical vault namespace through wrong storage."""

    pass


class StorageCorruptionError(RuntimeError):
    """Storage corruption detected (invalid JSON, hash mismatch, etc.)."""

    pass


class StorageRollbackDetected(RuntimeError):
    """Rollback attack detected via epoch regression."""

    pass


class StorageTamperDetected(RuntimeError):
    """Protected data was modified outside expected secure flow."""

    pass


__all__ = [
    "StorageSecurityError",
    "StorageConfigurationError",
    "NamespaceViolationError",
    "StorageCorruptionError",
    "StorageRollbackDetected",
    "StorageTamperDetected",
]
