"""Compatibility exports for storage manager.

Canonical implementation lives in modules.storage.manager.
"""

from modules.storage.manager import CRITICAL_VAULT_NAMESPACES, StorageManager

__all__ = [
    "StorageManager",
    "CRITICAL_VAULT_NAMESPACES",
]
