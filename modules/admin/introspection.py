"""
Admin introspection services (plugins, services, http, events, state, storage).

Moved from AdminModule for architectural clarity.
Behavior is unchanged. Implementations live in modules/admin/services/introspection.py.
"""

from modules.admin.services.introspection import (
    get_runtime_info,
    list_plugins,
    list_services,
    list_http_endpoints,
    list_events,
    get_dashboard,
    list_storage_namespaces,
    get_state,
    list_state_keys,
    get_state_value,
    list_operations_available,
    get_inventory,
)

__all__ = [
    "get_runtime_info",
    "list_plugins",
    "list_services",
    "list_http_endpoints",
    "list_events",
    "get_dashboard",
    "list_storage_namespaces",
    "get_state",
    "list_state_keys",
    "get_state_value",
    "list_operations_available",
    "get_inventory",
]
