"""Admin services - separated by domain."""

from .introspection import (
    get_runtime_info,
    list_plugins,
    list_services,
    list_http_endpoints,
    list_events,
    list_storage_namespaces,
    get_state,
    list_state_keys,
    get_state_value,
    list_operations_available,
)

__all__ = [
    "get_runtime_info",
    "list_plugins",
    "list_services",
    "list_http_endpoints",
    "list_events",
    "list_storage_namespaces",
    "get_state",
    "list_state_keys",
    "get_state_value",
    "list_operations_available",
]
