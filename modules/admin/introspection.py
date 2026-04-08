"""
Admin introspection services (plugins, services, http, ws, events, storage, operations, auth/integrations).

Moved from AdminModule for architectural clarity.
Implementations live in modules/admin/services/introspection.py.

NOTE: legacy state inspector surface was removed (use storage-backed inspector views).
"""

from modules.admin.services.introspection import (
    get_runtime_info,
    list_plugins,
    list_services,
    list_http_endpoints,
    list_ws_endpoints,
    list_events,
    list_storage_namespaces,
    get_storage_namespace_contents,
    list_operations_available,
    list_auth_flows,
    list_integrations,
    integrations_inspector_response,
    auth_inspector_response,
    inventory_inspector_response,
    inspector_auth_summary,
    dashboard_inspector_response,
    list_execution_traces,
    get_execution_trace,
    list_operation_executions,
    list_execution_retries,
    get_execution_tree,
    list_schedules,
    get_schedule,
    list_operation_schedules,
    list_capabilities,
    get_system_health,
    discover_manifests_for_inspector,
    get_plugin_details,
)

__all__ = [
    "get_runtime_info",
    "list_plugins",
    "list_services",
    "list_http_endpoints",
    "list_ws_endpoints",
    "list_events",
    "list_storage_namespaces",
    "get_storage_namespace_contents",
    "list_operations_available",
    "list_auth_flows",
    "list_integrations",
    "integrations_inspector_response",
    "auth_inspector_response",
    "inventory_inspector_response",
    "inspector_auth_summary",
    "dashboard_inspector_response",
    "list_execution_traces",
    "get_execution_trace",
    "list_operation_executions",
    "list_execution_retries",
    "get_execution_tree",
    "list_schedules",
    "get_schedule",
    "list_operation_schedules",
    "list_capabilities",
    "get_system_health",
    "discover_manifests_for_inspector",
    "get_plugin_details",
]
