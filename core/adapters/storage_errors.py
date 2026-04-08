"""Core storage errors: security, configuration, and integrity exceptions."""

from __future__ import annotations

import json


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


# Ожидаемые сбои storage/JSON на границе модулей (inspector, agent, API glue)
STORAGE_BOUNDARY_ERRORS: tuple[type[BaseException], ...] = (
    OSError,
    ValueError,
    TypeError,
    KeyError,
    json.JSONDecodeError,
    StorageCorruptionError,
    StorageRollbackDetected,
    StorageTamperDetected,
    StorageConfigurationError,
    StorageSecurityError,
    NamespaceViolationError,
)


__all__ = [
    "StorageSecurityError",
    "StorageConfigurationError",
    "NamespaceViolationError",
    "StorageCorruptionError",
    "StorageRollbackDetected",
    "StorageTamperDetected",
    "STORAGE_BOUNDARY_ERRORS",
]
