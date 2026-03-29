"""
AdminModule — Control Plane Host + Inspector Host.

Регистрирует только:
- GET /admin/v1/inspector/* (Inspector: read-only snapshot)
- POST/GET /admin/v1/operations (create / list / get / cancel / retry)
- /admin/v1/auth/* (auth)

Не содержит доменной логики, не регистрирует operations handlers, не знает плагины/домены.
"""

from pathlib import Path
from typing import Any, Optional
import json
import logging
import time

from core.runtime.runtime_module import RuntimeModule

# OrchestrationService (Docker/k8s абстракция)
from core.orchestration import OrchestrationService

logger = logging.getLogger(__name__)

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
from .http_endpoints import register_admin_core_http_endpoints
from .plugin_control_bindings import register_plugin_control_bindings
from .device_admin_bindings import register_device_admin_bindings
from .ssh_bindings import register_ssh_bindings
from .introspection import (
    get_runtime_info,
    list_plugins,
    list_services,
    list_http_endpoints,
    list_ws_endpoints,
    list_events,
    list_storage_namespaces,
    get_storage_namespace_contents,
    get_state,
    list_state_keys,
    get_state_value,
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
)
from .operations import (
    admin_operations_create,
    admin_operations_list,
    admin_operations_get,
    admin_operations_cancel,
    admin_operations_retry,
)

# Agent deploy (SSH bootstrap)
from modules.agent.services import admin_agent_deploy
# Auth services moved to AuthModule


class AdminModule(RuntimeModule):
    """
    Модуль административных endpoints.
    Тонкий сборщик: только регистрация сервисов и HTTP endpoints.
    """

    @property
    def name(self) -> str:
        return "admin"

    def __init__(self, runtime: Any):
        super().__init__(runtime)
        self._admin_started_at: Optional[float] = None
        self._registered_services: list[str] = []
        # OrchestrationService приходит через runtime DI.
        self._orchestration_service: Optional[OrchestrationService] = getattr(
            runtime, "orchestration_service", None
        )

    async def register(self) -> None:
        self._admin_started_at = time.time()
        self._registered_services = []
        register_admin_core_http_endpoints(self.context.http)

        # --- Webhook demo (C4) ---
        async def webhook_test_service(payload, **kwargs):
            import logging

            logger = logging.getLogger(__name__)
            logger.info(f"[C4 Webhook Demo] Received payload: {payload}")
            return {
                "ok": True,
                "message": "Webhook received and processed",
                "payload_type": str(type(payload).__name__),
                "payload_sample": str(payload)[:100] if payload else None,
            }

        await self.context.services.register("system.webhook_test", webhook_test_service)

        # --- Register admin services (glue: pass runtime via lambda) ---
        def wrap_introspection(fn, with_started_at: bool = False):
            if with_started_at:
                return lambda *args, **kw: fn(self.runtime, self._admin_started_at)
            return lambda *args, **kw: fn(self.runtime)

        def wrap_domain(fn):
            return lambda *args, **kw: fn(self.runtime, *args, **kw)

        def wrap_state_get():
            # Support both positional (console) and keyword (API) path param
            async def handler(key=None, **kw):
                k = key if key is not None else kw.get("key")
                return await get_state_value(self.runtime, k)

            return handler

        def wrap_execution_get():
            async def handler(execution_id=None, **kw):
                eid = (
                    execution_id
                    if execution_id is not None
                    else kw.get("execution_id") or kw.get("id")
                )
                return await get_execution_trace(self.runtime, eid)

            return handler

        def wrap_operation_executions():
            async def handler(operation_id=None, **kw):
                oid = (
                    operation_id
                    if operation_id is not None
                    else kw.get("operation_id") or kw.get("id")
                )
                return await list_operation_executions(self.runtime, oid)

            return handler

        def wrap_execution_retries():
            async def handler(execution_id=None, **kw):
                eid = (
                    execution_id
                    if execution_id is not None
                    else kw.get("execution_id") or kw.get("id")
                )
                return await list_execution_retries(self.runtime, eid)

            return handler

        def wrap_execution_tree():
            async def handler(execution_id=None, **kw):
                eid = (
                    execution_id
                    if execution_id is not None
                    else kw.get("execution_id") or kw.get("id")
                )
                return await get_execution_tree(self.runtime, eid)

            return handler

        def wrap_schedules():
            return lambda *args, **kw: list_schedules(self.runtime)

        def wrap_schedule_get():
            async def handler(schedule_id=None, **kw):
                sid = (
                    schedule_id
                    if schedule_id is not None
                    else kw.get("schedule_id") or kw.get("id")
                )
                return await get_schedule(self.runtime, sid)

            return handler

        def wrap_operation_schedules():
            async def handler(operation_id=None, **kw):
                oid = (
                    operation_id
                    if operation_id is not None
                    else kw.get("operation_id") or kw.get("id")
                )
                return await list_operation_schedules(self.runtime, oid)

            return handler

        def wrap_plugin_get():
            async def handler(name=None, **kw):
                n = name if name is not None else kw.get("name")
                return await get_plugin_details(self.runtime, n)

            return handler

        def wrap_storage_namespace_get():
            async def handler(namespace=None, **kw):
                ns = namespace if namespace is not None else kw.get("namespace")
                return await get_storage_namespace_contents(self.runtime, ns)

            return handler

        def wrap_credentials_list():
            async def handler(**kw):
                return await admin_credentials_list(self.runtime)

            return handler

        def wrap_credentials_create():
            async def handler(body=None, **kw):
                b = body if body is not None else kw.get("body")
                return await admin_credentials_create(self.runtime, b)

            return handler

        def wrap_credentials_get():
            async def handler(credential_id=None, **kw):
                cid = credential_id or kw.get("credential_id")
                return await admin_credentials_get(self.runtime, credential_id=cid)

            return handler

        def wrap_credentials_get_secret():
            async def handler(credential_id=None, **kw):
                cid = credential_id or kw.get("credential_id")
                return await admin_credentials_get_secret(
                    self.runtime, credential_id=cid
                )

            return handler

        def wrap_credentials_delete():
            async def handler(credential_id=None, **kw):
                cid = credential_id or kw.get("credential_id")
                return await admin_credentials_delete(self.runtime, credential_id=cid)

            return handler

        def wrap_credentials_update():
            async def handler(credential_id=None, body=None, **kw):
                cid = credential_id or kw.get("credential_id")
                b = body if body is not None else kw.get("body")
                return await admin_credentials_update(
                    self.runtime, credential_id=cid, body=b
                )

            return handler

        def wrap_credentials_connect():
            async def handler(credential_id=None, **kw):
                cid = credential_id or kw.get("credential_id")
                return await admin_credentials_connect(self.runtime, credential_id=cid)

            return handler

        def wrap_credentials_terminal_ws():
            async def handler(websocket=None, **kw):
                ws = websocket or kw.get("websocket")
                return await admin_credentials_terminal_ws(self.runtime, ws)

            return handler

        def wrap_credentials_terminal_sessions():
            async def handler(**kw):
                return await admin_credentials_terminal_sessions(self.runtime)

            return handler

        def wrap_credentials_terminal_session_close():
            async def handler(session_id: str, **kw):
                return await admin_credentials_terminal_session_close(
                    self.runtime, session_id=session_id
                )

            return handler

        def wrap_agent_deploy():
            async def handler(body=None, **kw):
                b = body if body is not None else kw.get("body")
                return await admin_agent_deploy(self.runtime, b)

            return handler

        def wrap_agent_terminal_start():
            async def handler(agent_id=None, body=None, **kw):
                aid = agent_id or kw.get("agent_id")
                b = body if body is not None else kw.get("body")
                if not await self.context.services.has_service(
                    "client_manager.start_agent_terminal"
                ):
                    raise RuntimeError("Agent terminal service not available")
                return await self.context.services.call(
                    "client_manager.start_agent_terminal", aid, b
                )

            return handler

        def wrap_agent_terminal_ws():
            async def handler(websocket=None, session_id=None, **kw):
                ws = websocket or kw.get("websocket")
                sid = session_id or kw.get("session_id")
                if not await self.context.services.has_service("client_manager.agent_terminal_ws"):
                    raise RuntimeError("Agent terminal websocket service not available")
                return await self.context.services.call(
                    "client_manager.agent_terminal_ws", websocket=ws, session_id=sid
                )

            return handler

        async def _marketplace_catalog(*args, **kw):
            """Список плагинов для маркетплейса: один захардкоженный файл catalog.json (ссылки на репо)."""
            catalog_path = (
                Path(__file__).resolve().parent.parent / "marketplace" / "catalog.json"
            )
            try:
                if catalog_path.exists():
                    data = json.loads(catalog_path.read_text(encoding="utf-8"))
                    return {"catalog": data if isinstance(data, list) else []}
            except Exception as e:
                logger.warning("marketplace catalog read failed: %s", e)
            return {"catalog": []}

        registrations = [
            (
                "admin.v1.runtime",
                wrap_introspection(get_runtime_info, with_started_at=True),
            ),
            ("admin.v1.plugins", wrap_introspection(list_plugins)),
            (
                "admin.v1.inspector.plugins.discover",
                wrap_introspection(discover_manifests_for_inspector),
            ),
            ("admin.v1.inspector.plugins.get", wrap_plugin_get()),
            ("admin.v1.services", wrap_introspection(list_services)),
            ("admin.v1.http", wrap_introspection(list_http_endpoints)),
            ("admin.v1.ws", wrap_introspection(list_ws_endpoints)),
            ("admin.v1.events", wrap_introspection(list_events)),
            ("admin.v1.storage", wrap_introspection(list_storage_namespaces)),
            ("admin.v1.storage.get", wrap_storage_namespace_get()),
            ("admin.v1.credentials.list", wrap_credentials_list()),
            ("admin.v1.credentials.create", wrap_credentials_create()),
            ("admin.v1.credentials.get", wrap_credentials_get()),
            ("admin.v1.credentials.get_secret", wrap_credentials_get_secret()),
            ("admin.v1.credentials.update", wrap_credentials_update()),
            ("admin.v1.credentials.delete", wrap_credentials_delete()),
            ("admin.v1.credentials.connect", wrap_credentials_connect()),
            ("admin.v1.credentials.terminal_ws", wrap_credentials_terminal_ws()),
            (
                "admin.v1.credentials.terminal_sessions",
                wrap_credentials_terminal_sessions(),
            ),
            (
                "admin.v1.credentials.terminal_session_close",
                wrap_credentials_terminal_session_close(),
            ),
            ("admin.v1.agents.terminal.start", wrap_agent_terminal_start()),
            ("admin.v1.agents.terminal.ws", wrap_agent_terminal_ws()),
            ("admin.v1.state", wrap_introspection(get_state)),
            ("admin.v1.state.keys", wrap_introspection(list_state_keys)),
            ("admin.v1.state.get", wrap_state_get()),
            (
                "admin.v1.inspector.operations",
                wrap_introspection(list_operations_available),
            ),
            ("admin.v1.inspector.auth", wrap_introspection(auth_inspector_response)),
            (
                "admin.v1.inspector.integrations",
                wrap_introspection(integrations_inspector_response),
            ),
            (
                "admin.v1.inspector.inventory",
                wrap_introspection(inventory_inspector_response),
            ),
            ("admin.v1.inspector.capabilities", wrap_introspection(list_capabilities)),
            (
                "admin.v1.inspector.executions",
                wrap_introspection(list_execution_traces),
            ),
            ("admin.v1.inspector.executions.get", wrap_execution_get()),
            ("admin.v1.inspector.operations.executions", wrap_operation_executions()),
            ("admin.v1.inspector.executions.retries", wrap_execution_retries()),
            ("admin.v1.inspector.executions.tree", wrap_execution_tree()),
            ("admin.v1.inspector.schedules", wrap_schedules()),
            ("admin.v1.inspector.schedules.get", wrap_schedule_get()),
            ("admin.v1.inspector.operations.schedules", wrap_operation_schedules()),
            ("admin.v1.inspector.system_health", wrap_introspection(get_system_health)),
            (
                "admin.v1.inspector.dashboard",
                wrap_introspection(dashboard_inspector_response),
            ),
            ("admin.v1.marketplace.catalog", _marketplace_catalog),
            # Admin devices read-only proxy services (kept for Admin UI compatibility)
            (
                "admin.v1.devices.list",
                wrap_domain(
                    __import__(
                        "modules.admin.devices", fromlist=["admin_devices_list"]
                    ).admin_devices_list
                ),
            ),
            (
                "admin.v1.devices.get",
                wrap_domain(
                    __import__(
                        "modules.admin.devices", fromlist=["admin_devices_get"]
                    ).admin_devices_get
                ),
            ),
            (
                "admin.v1.devices.list_external",
                wrap_domain(
                    __import__(
                        "modules.admin.devices",
                        fromlist=["admin_devices_list_external"],
                    ).admin_devices_list_external
                ),
            ),
            (
                "admin.v1.devices.list_mappings",
                wrap_domain(
                    __import__(
                        "modules.admin.devices",
                        fromlist=["admin_devices_list_mappings"],
                    ).admin_devices_list_mappings
                ),
            ),
            (
                "admin.v1.devices.get_external_for_device",
                wrap_domain(
                    __import__(
                        "modules.admin.devices",
                        fromlist=["admin_devices_get_external_for_device"],
                    ).admin_devices_get_external_for_device
                ),
            ),
            ("admin.operations.create", wrap_domain(admin_operations_create)),
            ("admin.operations.list", wrap_domain(admin_operations_list)),
            ("admin.operations.get", wrap_domain(admin_operations_get)),
            ("admin.operations.cancel", wrap_domain(admin_operations_cancel)),
            ("admin.operations.retry", wrap_domain(admin_operations_retry)),
            # Admin SSH deploy endpoint is now owned by AgentControlPlaneModule (admin.agent.deploy)
            # Auth services moved to AuthModule
        ]

        # Public services now managed by AuthModule
        for name, handler in registrations:
            try:
                # Allow internal calls to inspector/admin.v1.* services without admin ctx
                if name.startswith("admin.v1."):
                    admin_only = False
                else:
                    # Non-inspector admin services require admin auth (auth services in AuthModule)
                    admin_only = True
                await self.context.services.register_with_acl(name, handler, admin_only=admin_only)
                self._registered_services.append(name)
            except ValueError:
                continue

        self._registered_services.extend(
            await register_plugin_control_bindings(
                self.runtime,
                self.context,
                self._orchestration_service,
            )
        )
        # Прокидываем runtime в RuntimeContext, чтобы device_admin_bindings мог использовать runtime.kernel_context.
        setattr(self.context, "runtime", self.runtime)
        self._registered_services.extend(
            await register_device_admin_bindings(self.context)
        )
        self._registered_services.extend(
            await register_ssh_bindings(self.runtime, self.context)
        )

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        for service_name in self._registered_services:
            try:
                await self.context.services.unregister(service_name)
            except Exception:
                pass
        self._registered_services.clear()
