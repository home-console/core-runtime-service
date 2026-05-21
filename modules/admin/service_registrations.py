"""
Декларативный список admin/inspector сервисов и glue-handlers.

Раньше десятки inline closure жили в `AdminModule.register` (проблема D3).
Сейчас единая точка: `build_admin_registrations()` + фабрики из `handler_factory.py`.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from .credentials_handlers import (
    admin_credentials_list,
    admin_credentials_create,
    admin_credentials_get,
    admin_credentials_get_secret,
    admin_credentials_update,
    admin_credentials_delete,
    admin_credentials_connect,
    admin_credentials_terminal_ws,
    admin_credentials_terminal_sessions,
    admin_credentials_terminal_session_close,
)
from .devices import (
    admin_devices_list,
    admin_devices_get,
    admin_devices_list_external,
    admin_devices_list_mappings,
    admin_devices_get_external_for_device,
)
from .handler_factory import (
    make_runtime_handler,
    make_runtime_handler_positional,
    make_service_call_handler_kwargs,
    make_service_call_handler_positional,
)
from .introspection import (
    get_runtime_info,
    list_plugins,
    list_services,
    list_http_endpoints,
    list_ws_endpoints,
    list_events,
    list_storage_namespaces,
    get_storage_namespace_contents,
    list_operations_available,
    integrations_inspector_response,
    auth_inspector_response,
    inventory_inspector_response,
    dashboard_inspector_response,
    get_system_health,
    list_execution_traces,
    get_execution_trace,
    list_operation_executions,
    list_execution_retries,
    get_execution_tree,
    list_schedules,
    get_schedule,
    list_operation_schedules,
    list_capabilities,
    discover_manifests_for_inspector,
    get_plugin_details,
    get_plugin_ui_contributions,
    get_plugin_ui_config,
    set_plugin_ui_config,
    invoke_plugin_service,
    list_dashboard_cards,
)
from .operations import (
    admin_operations_create,
    admin_operations_list,
    admin_operations_get,
    admin_operations_cancel,
    admin_operations_retry,
)


def build_admin_registrations(
    *,
    runtime: Any,
    context: Any,
    get_admin_started_at: Callable[[], float | None],
    marketplace_catalog_handler: Callable[..., Awaitable[Any]],
) -> list[tuple[str, Callable[..., Awaitable[Any]]]]:
    async def _runtime_info(*args: Any, **kw: Any) -> Any:
        return await get_runtime_info(runtime, get_admin_started_at())

    execution_get = make_runtime_handler_positional(
        get_execution_trace,
        runtime=runtime,
        required=[(0, ("execution_id", "id"))],
    )
    execution_retries = make_runtime_handler_positional(
        list_execution_retries,
        runtime=runtime,
        required=[(0, ("execution_id", "id"))],
    )
    execution_tree = make_runtime_handler_positional(
        get_execution_tree,
        runtime=runtime,
        required=[(0, ("execution_id", "id"))],
    )
    schedule_get = make_runtime_handler_positional(
        get_schedule,
        runtime=runtime,
        required=[(0, ("schedule_id", "id"))],
    )
    operation_executions = make_runtime_handler_positional(
        list_operation_executions,
        runtime=runtime,
        required=[(0, ("operation_id", "id"))],
    )
    operation_schedules = make_runtime_handler_positional(
        list_operation_schedules,
        runtime=runtime,
        required=[(0, ("operation_id", "id"))],
    )
    plugin_get = make_runtime_handler_positional(
        get_plugin_details,
        runtime=runtime,
        required=[(0, ("name",))],
    )
    plugin_ui = make_runtime_handler_positional(
        get_plugin_ui_contributions,
        runtime=runtime,
        required=[(0, ("name",))],
    )
    plugin_config_get = make_runtime_handler_positional(
        get_plugin_ui_config,
        runtime=runtime,
        required=[(0, ("name",))],
    )
    plugin_config_set = make_runtime_handler(
        set_plugin_ui_config,
        runtime=runtime,
        params=[
            ("plugin_name", 0, ("name", "plugin_name"), None),
            ("body", 0, ("body",), None),
        ],
    )
    plugin_invoke = make_runtime_handler(
        invoke_plugin_service,
        runtime=runtime,
        params=[
            ("plugin_name", 0, ("name", "plugin_name"), None),
            ("body", 0, ("body",), None),
        ],
    )
    dashboard_cards_list = make_runtime_handler(
        list_dashboard_cards,
        runtime=runtime,
    )
    storage_namespace_get = make_runtime_handler_positional(
        get_storage_namespace_contents,
        runtime=runtime,
        required=[(0, ("namespace",))],
    )

    credentials_list = make_runtime_handler(admin_credentials_list, runtime=runtime)
    credentials_create = make_runtime_handler(
        admin_credentials_create,
        runtime=runtime,
        params=[("body", 0, ("body",), None)],
    )
    credentials_get = make_runtime_handler(
        admin_credentials_get,
        runtime=runtime,
        params=[("credential_id", 0, ("credential_id",), None)],
    )
    credentials_get_secret = make_runtime_handler(
        admin_credentials_get_secret,
        runtime=runtime,
        params=[("credential_id", 0, ("credential_id",), None)],
    )
    credentials_update = make_runtime_handler(
        admin_credentials_update,
        runtime=runtime,
        params=[
            ("credential_id", 0, ("credential_id",), None),
            ("body", 1, ("body",), None),
        ],
    )
    credentials_delete = make_runtime_handler(
        admin_credentials_delete,
        runtime=runtime,
        params=[("credential_id", 0, ("credential_id",), None)],
    )
    credentials_connect = make_runtime_handler(
        admin_credentials_connect,
        runtime=runtime,
        params=[("credential_id", 0, ("credential_id",), None)],
    )
    credentials_terminal_ws = make_runtime_handler_positional(
        admin_credentials_terminal_ws,
        runtime=runtime,
        required=[(0, ("websocket",))],
    )
    credentials_terminal_sessions = make_runtime_handler(
        admin_credentials_terminal_sessions,
        runtime=runtime,
    )
    credentials_terminal_session_close = make_runtime_handler_positional(
        admin_credentials_terminal_session_close,
        runtime=runtime,
        required=[(0, ("session_id",))],
    )

    agent_terminal_start = make_service_call_handler_positional(
        services=context.services,
        target_service="client_manager.start_agent_terminal",
        required=[(0, ("agent_id",))],
        optional=[(1, ("body",), None)],
        unavailable_response={
            "ok": False,
            "error": "Agent terminal service is unavailable",
            "code": "SERVICE_UNAVAILABLE",
        },
    )

    agent_terminal_ws = make_service_call_handler_kwargs(
        services=context.services,
        target_service="client_manager.agent_terminal_ws",
        params=[
            ("websocket", 0, ("websocket",), None),
            ("session_id", 1, ("session_id",), None),
        ],
        unavailable_response={
            "ok": False,
            "error": "Agent terminal websocket service is unavailable",
            "code": "SERVICE_UNAVAILABLE",
        },
        close_ws_on_unavailable=True,
        ws_close_code=1013,
        ws_close_reason="Agent terminal service unavailable",
    )

    return [
        ("admin.v1.runtime", _runtime_info),
        ("admin.v1.plugins", make_runtime_handler(list_plugins, runtime=runtime)),
        (
            "admin.v1.inspector.plugins.discover",
            make_runtime_handler(discover_manifests_for_inspector, runtime=runtime),
        ),
        ("admin.v1.inspector.plugins.get", plugin_get),
        ("admin.v1.inspector.plugins.ui", plugin_ui),
        ("admin.v1.inspector.plugins.config.get", plugin_config_get),
        ("admin.v1.inspector.plugins.config.set", plugin_config_set),
        ("admin.v1.inspector.plugins.invoke", plugin_invoke),
        ("admin.v1.inspector.dashboard_cards", dashboard_cards_list),
        ("admin.v1.services", make_runtime_handler(list_services, runtime=runtime)),
        ("admin.v1.http", make_runtime_handler(list_http_endpoints, runtime=runtime)),
        ("admin.v1.ws", make_runtime_handler(list_ws_endpoints, runtime=runtime)),
        ("admin.v1.events", make_runtime_handler(list_events, runtime=runtime)),
        ("admin.v1.storage", make_runtime_handler(list_storage_namespaces, runtime=runtime)),
        ("admin.v1.storage.get", storage_namespace_get),
        ("admin.v1.credentials.list", credentials_list),
        ("admin.v1.credentials.create", credentials_create),
        ("admin.v1.credentials.get", credentials_get),
        ("admin.v1.credentials.get_secret", credentials_get_secret),
        ("admin.v1.credentials.update", credentials_update),
        ("admin.v1.credentials.delete", credentials_delete),
        ("admin.v1.credentials.connect", credentials_connect),
        ("admin.v1.credentials.terminal_ws", credentials_terminal_ws),
        ("admin.v1.credentials.terminal_sessions", credentials_terminal_sessions),
        (
            "admin.v1.credentials.terminal_session_close",
            credentials_terminal_session_close,
        ),
        ("admin.v1.agents.terminal.start", agent_terminal_start),
        ("admin.v1.agents.terminal.ws", agent_terminal_ws),
        (
            "admin.v1.inspector.operations",
            make_runtime_handler(list_operations_available, runtime=runtime),
        ),
        ("admin.v1.inspector.auth", make_runtime_handler(auth_inspector_response, runtime=runtime)),
        (
            "admin.v1.inspector.integrations",
            make_runtime_handler(integrations_inspector_response, runtime=runtime),
        ),
        (
            "admin.v1.inspector.inventory",
            make_runtime_handler(inventory_inspector_response, runtime=runtime),
        ),
        ("admin.v1.inspector.capabilities", make_runtime_handler(list_capabilities, runtime=runtime)),
        (
            "admin.v1.inspector.executions",
            make_runtime_handler(list_execution_traces, runtime=runtime),
        ),
        ("admin.v1.inspector.executions.get", execution_get),
        ("admin.v1.inspector.operations.executions", operation_executions),
        ("admin.v1.inspector.executions.retries", execution_retries),
        ("admin.v1.inspector.executions.tree", execution_tree),
        ("admin.v1.inspector.schedules", make_runtime_handler(list_schedules, runtime=runtime)),
        ("admin.v1.inspector.schedules.get", schedule_get),
        ("admin.v1.inspector.operations.schedules", operation_schedules),
        ("admin.v1.inspector.system_health", make_runtime_handler(get_system_health, runtime=runtime)),
        (
            "admin.v1.inspector.dashboard",
            make_runtime_handler(dashboard_inspector_response, runtime=runtime),
        ),
        ("admin.v1.marketplace.catalog", marketplace_catalog_handler),
        ("admin.v1.devices.list", make_runtime_handler(admin_devices_list, runtime=runtime)),
        (
            "admin.v1.devices.get",
            make_runtime_handler(
                admin_devices_get,
                runtime=runtime,
                params=[("id", 0, ("id", "device_id", "deviceId"), None)],
            ),
        ),
        ("admin.v1.devices.list_external", make_runtime_handler(admin_devices_list_external, runtime=runtime)),
        ("admin.v1.devices.list_mappings", make_runtime_handler(admin_devices_list_mappings, runtime=runtime)),
        (
            "admin.v1.devices.get_external_for_device",
            make_runtime_handler(
                admin_devices_get_external_for_device,
                runtime=runtime,
                params=[("id", 0, ("id", "device_id", "deviceId"), None)],
            ),
        ),
        (
            "admin.operations.create",
            make_runtime_handler(admin_operations_create, runtime=runtime, params=[("body", 0, ("body",), None)]),
        ),
        ("admin.operations.list", make_runtime_handler(admin_operations_list, runtime=runtime)),
        ("admin.operations.get", make_runtime_handler(admin_operations_get, runtime=runtime)),
        ("admin.operations.cancel", make_runtime_handler(admin_operations_cancel, runtime=runtime)),
        (
            "admin.operations.retry",
            make_runtime_handler(admin_operations_retry, runtime=runtime, params=[("body", 0, ("body",), None)]),
        ),
    ]

