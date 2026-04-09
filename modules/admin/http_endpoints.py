"""
HTTP endpoint registrations for AdminModule.

Отдельный helper, чтобы не держать всю таблицу endpoint'ов внутри одного большого
модуля регистрации.
"""

from typing import Any

from core.http.models import HttpEndpoint, EndpointAuthConfig


def register_admin_core_http_endpoints(http_registry: Any) -> None:
    """Register read-only inspector and credentials/admin endpoints."""
    _admin_read = EndpointAuthConfig(required_scopes=["admin.read"])
    _admin_write = EndpointAuthConfig(required_scopes=["admin.write"])
    inspector_endpoints = [
        ("/admin/v1/inspector/dashboard", "admin.v1.inspector.dashboard", "Inspector: dashboard summary"),
        ("/admin/v1/inspector/runtime", "admin.v1.runtime", "Inspector: runtime info"),
        ("/admin/v1/inspector/plugins", "admin.v1.plugins", "Inspector: list plugins"),
        ("/admin/v1/inspector/services", "admin.v1.services", "Inspector: list services"),
        ("/admin/v1/inspector/http", "admin.v1.http", "Inspector: list HTTP endpoints"),
        ("/admin/v1/inspector/ws", "admin.v1.ws", "Inspector: list WebSocket endpoints"),
        ("/admin/v1/inspector/events", "admin.v1.events", "Inspector: list event subscriptions"),
        ("/admin/v1/inspector/storage", "admin.v1.storage", "Inspector: list storage namespaces"),
        ("/admin/v1/inspector/operations", "admin.v1.inspector.operations", "Inspector: available operation types"),
        ("/admin/v1/inspector/executions", "admin.v1.inspector.executions", "Inspector: list execution traces"),
        ("/admin/v1/inspector/auth", "admin.v1.inspector.auth", "Inspector: auth flows (OAuth/device auth, etc.)"),
        ("/admin/v1/inspector/integrations", "admin.v1.inspector.integrations", "Inspector: integrations (connect/disconnect state, actions)"),
        ("/admin/v1/inspector/inventory", "admin.v1.inspector.inventory", "Inspector: devices inventory (items, mappings, external by provider)"),
        ("/admin/v1/inspector/system_health", "admin.v1.inspector.system_health", "Inspector: system health (metrics, resource usage)"),
    ]
    for path, service, description in inspector_endpoints:
        http_registry.register(HttpEndpoint(
            method="GET",
            path=path,
            service=service,
            description=description,
            auth_config=_admin_read,
        ))

    extra_endpoints = [
        HttpEndpoint(
            method="GET",
            path="/admin/v1/inspector/plugins/discover",
            service="admin.v1.inspector.plugins.discover",
            description="Inspector: discover plugins on disk (manifests, load_order)",
            auth_config=_admin_read,
        ),
        HttpEndpoint(
            method="GET",
            path="/admin/v1/inspector/plugins/{name}",
            service="admin.v1.inspector.plugins.get",
            description="Inspector: get single plugin details (loaded + manifest)",
            auth_config=_admin_read,
        ),
        HttpEndpoint(
            method="GET",
            path="/admin/v1/marketplace/catalog",
            service="admin.v1.marketplace.catalog",
            description="Marketplace: список интеграций (из manifest’ов плагинов)",
            auth_config=_admin_read,
        ),
        HttpEndpoint(
            method="GET",
            path="/admin/v1/inspector/storage/{namespace}",
            service="admin.v1.storage.get",
            description="Inspector: get storage namespace contents (keys + values)",
            auth_config=_admin_read,
        ),
        HttpEndpoint(
            method="GET",
            path="/admin/v1/credentials",
            service="admin.v1.credentials.list",
            description="Admin: list credentials",
            auth_config=_admin_read,
        ),
        HttpEndpoint(
            method="POST",
            path="/admin/v1/credentials",
            service="admin.v1.credentials.create",
            description="Admin: create credential",
            auth_config=_admin_write,
        ),
        HttpEndpoint(
            method="GET",
            path="/admin/v1/credentials/{credential_id}",
            service="admin.v1.credentials.get",
            description="Admin: get credential by id",
            auth_config=_admin_read,
        ),
        HttpEndpoint(
            method="GET",
            path="/admin/v1/credentials/{credential_id}/secret",
            service="admin.v1.credentials.get_secret",
            description="Admin: get credential secret (for export)",
            auth_config=_admin_read,
        ),
        HttpEndpoint(
            method="PUT",
            path="/admin/v1/credentials/{credential_id}",
            service="admin.v1.credentials.update",
            description="Admin: update credential",
            auth_config=_admin_write,
        ),
        HttpEndpoint(
            method="DELETE",
            path="/admin/v1/credentials/{credential_id}",
            service="admin.v1.credentials.delete",
            description="Admin: delete credential",
            auth_config=_admin_write,
        ),
        HttpEndpoint(
            method="POST",
            path="/admin/v1/credentials/{credential_id}/connect",
            service="admin.v1.credentials.connect",
            description="Admin: подключиться к хосту по креду из БД (SSH)",
            auth_config=_admin_write,
        ),
        HttpEndpoint(
            method="GET",
            path="/admin/v1/credentials/terminal/sessions",
            service="admin.v1.credentials.terminal_sessions",
            description="Admin: список активных SSH терминальных сессий",
            auth_config=_admin_read,
        ),
        HttpEndpoint(
            method="DELETE",
            path="/admin/v1/credentials/terminal/sessions/{session_id}",
            service="admin.v1.credentials.terminal_session_close",
            description="Admin: закрыть SSH терминальную сессию по id",
            auth_config=_admin_write,
        ),
        HttpEndpoint(
            path="/admin/v1/credentials/terminal",
            service="admin.v1.credentials.terminal_ws",
            websocket=True,
            description="Admin: WebSocket терминал по креду (?credential_id=...)",
            auth_config=_admin_write,
        ),
        HttpEndpoint(
            method="POST",
            path="/admin/v1/agents/{agent_id}/terminal/start",
            service="admin.v1.agents.terminal.start",
            description="Admin: запустить терминальную сессию на агенте",
            auth_config=_admin_write,
        ),
        HttpEndpoint(
            path="/admin/v1/agents/terminal/ws/{session_id}",
            service="admin.v1.agents.terminal.ws",
            websocket=True,
            description="Admin: WebSocket attach к терминальной сессии агента",
            auth_config=_admin_write,
        ),
        HttpEndpoint(
            method="GET",
            path="/admin/v1/inspector/executions/{execution_id}",
            service="admin.v1.inspector.executions.get",
            description="Inspector: get execution trace by id",
            auth_config=_admin_read,
        ),
        HttpEndpoint(
            method="GET",
            path="/admin/v1/inspector/operations/{operation_id}/executions",
            service="admin.v1.inspector.operations.executions",
            description="Inspector: list executions for operation",
            auth_config=_admin_read,
        ),
        HttpEndpoint(
            method="GET",
            path="/admin/v1/inspector/executions/{execution_id}/retries",
            service="admin.v1.inspector.executions.retries",
            description="Inspector: list retries for execution",
            auth_config=_admin_read,
        ),
        HttpEndpoint(
            method="GET",
            path="/admin/v1/inspector/executions/{execution_id}/tree",
            service="admin.v1.inspector.executions.tree",
            description="Inspector: execution retry tree",
            auth_config=_admin_read,
        ),
        HttpEndpoint(
            method="GET",
            path="/admin/v1/inspector/schedules",
            service="admin.v1.inspector.schedules",
            description="Inspector: list execution schedules",
            auth_config=_admin_read,
        ),
        HttpEndpoint(
            method="GET",
            path="/admin/v1/inspector/schedules/{schedule_id}",
            service="admin.v1.inspector.schedules.get",
            description="Inspector: get execution schedule by id",
            auth_config=_admin_read,
        ),
        HttpEndpoint(
            method="GET",
            path="/admin/v1/inspector/operations/{operation_id}/schedules",
            service="admin.v1.inspector.operations.schedules",
            description="Inspector: list schedules for operation",
            auth_config=_admin_read,
        ),
    ]

    for endpoint in extra_endpoints:
        http_registry.register(endpoint)
