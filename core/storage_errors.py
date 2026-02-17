"""
Storage-specific security and configuration errors.

P0: Prevent namespace injection and storage mode violations.
"""


class StorageSecurityError(Exception):
    """Storage security violation."""
    pass


class StorageConfigurationError(Exception):
    """Invalid storage configuration."""
    pass


class NamespaceViolationError(StorageSecurityError):
    """Attempt to write critical vault namespace through wrong storage."""
    pass
