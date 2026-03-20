"""
Canonical storage domain import surface.

This package provides a stable storage API surface without conflicting with
core/storage.py module naming.
"""

from core.storage import Storage
from core.storage_mirror import StorageWithStateMirror
from core.storage_port import CoreStoragePort, VaultStoragePort, StorageStack
from core.storage_manager import StorageManager, CRITICAL_VAULT_NAMESPACES
from core.storage_startup import StorageStartupChecker
from core.storage_abstraction import IStorageBackend
from core.storage_errors import (
    StorageSecurityError,
    StorageConfigurationError,
    NamespaceViolationError,
)
from core.storage_exceptions import (
    StorageCorruptionError,
    StorageRollbackDetected,
    StorageTamperDetected,
)
from core.storage_migrate import migrate_to_dual_mode, check_migration_status
from core.storage_crypto import sha256_json

__all__ = [
    "Storage",
    "StorageWithStateMirror",
    "CoreStoragePort",
    "VaultStoragePort",
    "StorageStack",
    "StorageManager",
    "CRITICAL_VAULT_NAMESPACES",
    "StorageStartupChecker",
    "IStorageBackend",
    "StorageSecurityError",
    "StorageConfigurationError",
    "NamespaceViolationError",
    "StorageCorruptionError",
    "StorageRollbackDetected",
    "StorageTamperDetected",
    "migrate_to_dual_mode",
    "check_migration_status",
    "sha256_json",
]
