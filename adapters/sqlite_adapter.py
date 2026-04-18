"""
Backward-compatible alias for SQLiteAdapter.

Prefer importing from `core.adapters.sqlite_adapter`.
"""

from core.adapters.sqlite_adapter import SQLiteAdapter

__all__ = ["SQLiteAdapter"]

