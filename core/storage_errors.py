"""Core storage security and configuration errors."""


class StorageSecurityError(Exception):
    """Storage security violation."""

    pass


class StorageConfigurationError(Exception):
    """Invalid storage configuration."""

    pass


class NamespaceViolationError(StorageSecurityError):
    """Attempt to write critical vault namespace through wrong storage."""

    pass


__all__ = ["StorageSecurityError", "StorageConfigurationError", "NamespaceViolationError"]
