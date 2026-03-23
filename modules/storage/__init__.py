"""Storage module exports."""

from .abstraction import IStorageBackend
from .crypto import (
    calculate_namespace_root,
    calculate_storage_root,
    canonical_json,
    merkle_root,
    sha256_bytes,
    sha256_json,
    sha256_string,
)
from .errors import (
    NamespaceViolationError,
    StorageConfigurationError,
    StorageSecurityError,
)
from .exceptions import (
    StorageCorruptionError,
    StorageRollbackDetected,
    StorageTamperDetected,
)
from .manager import CRITICAL_VAULT_NAMESPACES, StorageManager
from .mirror import StorageWithStateMirror
from .port import CoreStoragePort, StorageStack, VaultStoragePort
from .secure import (
    CRITICAL_NAMESPACES,
    PROTECTED_NAMESPACES,
    SYSTEM_NAMESPACES,
    SecureStorageWrapper,
)
from .factory import (
    build_storage_stack,
    create_storage_adapter,
    create_storage_manager,
)
from .startup import StorageInitializer, StorageStartupChecker
from .storage import Storage

__all__ = [
    "StorageSecurityError",
    "StorageConfigurationError",
    "NamespaceViolationError",
    "canonical_json",
    "sha256_bytes",
    "sha256_json",
    "sha256_string",
    "merkle_root",
    "calculate_namespace_root",
    "calculate_storage_root",
    "StorageCorruptionError",
    "StorageRollbackDetected",
    "StorageTamperDetected",
    "SecureStorageWrapper",
    "CRITICAL_NAMESPACES",
    "SYSTEM_NAMESPACES",
    "PROTECTED_NAMESPACES",
    "StorageManager",
    "CRITICAL_VAULT_NAMESPACES",
    "StorageWithStateMirror",
    "CoreStoragePort",
    "VaultStoragePort",
    "StorageStack",
    "StorageStartupChecker",
    "StorageInitializer",
    "IStorageBackend",
    "Storage",
    "create_storage_adapter",
    "create_storage_manager",
    "build_storage_stack",
]
