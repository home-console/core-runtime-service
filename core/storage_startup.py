"""
Compatibility shim for `core.storage_startup`.

Some code imports `core.storage_startup` but implementation lives in
`modules.storage.startup` after refactor. This module re-exports the
classes to maintain backwards compatibility.
"""

from modules.storage.startup import StorageStartupChecker, StorageInitializer

__all__ = ["StorageStartupChecker", "StorageInitializer"]
