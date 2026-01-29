"""Operations module — operation lifecycle management."""

from .module import OperationsModule
from .handlers import (
    handle_device_set_state,
    handle_yandex_sync,
    handle_yandex_check_online,
    handle_oauth_refresh,
    handle_mappings_create,
    handle_mappings_delete,
    handle_mappings_auto,
)
from .router import create_operations_router

__all__ = [
    "OperationsModule",
    "create_operations_router",
    "handle_device_set_state",
    "handle_yandex_sync",
    "handle_yandex_check_online",
    "handle_oauth_refresh",
    "handle_mappings_create",
    "handle_mappings_delete",
    "handle_mappings_auto",
]
