"""Application-level storage stack wiring helpers."""

from modules.storage.factory import (
    build_storage_stack,
    create_storage_adapter,
    create_storage_manager,
)

__all__ = [
    "create_storage_adapter",
    "create_storage_manager",
    "build_storage_stack",
]
