"""Compatibility exports for storage ports.

Canonical implementation lives in modules.storage.port.
"""

from modules.storage.port import CoreStoragePort, StorageStack, VaultStoragePort

__all__ = [
    "CoreStoragePort",
    "VaultStoragePort",
    "StorageStack",
]
