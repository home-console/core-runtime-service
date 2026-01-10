"""
Адаптеры для работы с внешними системами (storage, etc).
"""

from .storage_adapter import StorageAdapter
from .sqlite_adapter import SQLiteAdapter

try:
    from .postgresql_adapter import PostgreSQLAdapter
    __all__ = [
        "StorageAdapter",
        "SQLiteAdapter",
        "PostgreSQLAdapter",
    ]
except ImportError:
    # PostgreSQL адаптер недоступен, если asyncpg не установлен
    __all__ = [
        "StorageAdapter",
        "SQLiteAdapter",
    ]
