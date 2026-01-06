"""
Адаптеры для работы с внешними системами (storage, etc).
"""

from .storage_adapter import StorageAdapter
from .sqlite_adapter import SQLiteAdapter

__all__ = [
    "StorageAdapter",
    "SQLiteAdapter",
]
