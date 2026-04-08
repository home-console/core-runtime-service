"""Admin services - separated by domain."""

from .introspection import (
    get_runtime_info,
    list_plugins,
    list_services,
    list_http_endpoints,
    list_events,
    list_storage_namespaces,
    get_storage_namespace_contents,
    list_operations_available,
)

__all__ = [
    "get_runtime_info",
    "list_plugins",
    "list_services",
    "list_http_endpoints",
    "list_events",
    "list_storage_namespaces",
    "get_storage_namespace_contents",
    "list_operations_available",
]
