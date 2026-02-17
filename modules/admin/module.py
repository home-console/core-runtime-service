"""
AdminModule — Control Plane Host + Inspector Host.

Регистрирует только:
- GET /admin/v1/inspector/* (Inspector: read-only snapshot)
- POST/GET /admin/v1/operations (create / list / get / cancel / retry)
- /admin/v1/auth/* (auth)

Не содержит доменной логики, не регистрирует operations handlers, не знает плагины/домены.
"""

from typing import Any, Optional
import time

from core.runtime_module import RuntimeModule
from core.http_registry import HttpEndpoint

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
    list_auth_flows,
    list_integrations,
    integrations_inspector_response,
    auth_inspector_response,
    inventory_inspector_response,
    inspector_auth_summary,
    list_execution_traces,
    get_execution_trace,
    list_operation_executions,
    list_execution_retries,
    get_execution_tree,
    list_schedules,
    get_schedule,
    list_operation_schedules,
    list_capabilities,
)
from .operations import (
    admin_operations_create,
    admin_operations_list,
    admin_operations_get,
    admin_operations_cancel,
    admin_operations_retry,
)
from .auth import (
    admin_auth_create_api_key,
    admin_auth_list_api_keys,
    admin_auth_create_user,
    admin_auth_list_users,
    admin_auth_initialize,
    admin_auth_login,
    admin_auth_refresh,
    admin_auth_set_password,
    admin_auth_change_password,
    admin_auth_list_sessions,
    admin_auth_revoke_session,
    admin_auth_revoke_all_sessions,
    admin_auth_revoke_api_key,
    admin_auth_rotate_api_key,
    admin_auth_me,
)


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

    async def register(self) -> None:
        self._admin_started_at = time.time()
        self._registered_services = []

        # --- HTTP: Inspector (read-only snapshot) ---
        inspector_endpoints = [
            ("/admin/v1/inspector/runtime", "admin.v1.runtime", "Inspector: runtime info"),
            ("/admin/v1/inspector/plugins", "admin.v1.plugins", "Inspector: list plugins"),
            ("/admin/v1/inspector/services", "admin.v1.services", "Inspector: list services"),
            ("/admin/v1/inspector/http", "admin.v1.http", "Inspector: list HTTP endpoints"),
            ("/admin/v1/inspector/events", "admin.v1.events", "Inspector: list event subscriptions"),
            ("/admin/v1/inspector/storage", "admin.v1.storage", "Inspector: list storage namespaces"),
            ("/admin/v1/inspector/state", "admin.v1.state", "Inspector: get all state"),
            ("/admin/v1/inspector/state/keys", "admin.v1.state.keys", "Inspector: list state keys"),
            ("/admin/v1/inspector/operations", "admin.v1.inspector.operations", "Inspector: available operation types"),
            ("/admin/v1/inspector/executions", "admin.v1.inspector.executions", "Inspector: list execution traces"),
            ("/admin/v1/inspector/auth", "admin.v1.inspector.auth", "Inspector: auth flows (OAuth/device auth, etc.)"),
            ("/admin/v1/inspector/integrations", "admin.v1.inspector.integrations", "Inspector: integrations (connect/disconnect state, actions)"),
            ("/admin/v1/inspector/inventory", "admin.v1.inspector.inventory", "Inspector: devices inventory (items, mappings, external by provider)"),
            ("/admin/v1/inspector/system_health", "admin.v1.inspector.system_health", "Inspector: system health (metrics, resource usage)"),
        ]
        for path, service, description in inspector_endpoints:
            self.runtime.http.register(HttpEndpoint(
                method="GET",
                path=path,
                service=service,
                description=description
            ))
        self.runtime.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/inspector/state/{key}",
            service="admin.v1.state.get",
            description="Inspector: get state value by key"
        ))
        self.runtime.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/inspector/executions/{execution_id}",
            service="admin.v1.inspector.executions.get",
            description="Inspector: get execution trace by id",
        ))
        self.runtime.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/inspector/operations/{operation_id}/executions",
            service="admin.v1.inspector.operations.executions",
            description="Inspector: list executions for operation",
        ))
        self.runtime.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/inspector/executions/{execution_id}/retries",
            service="admin.v1.inspector.executions.retries",
            description="Inspector: list retries for execution",
        ))
        self.runtime.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/inspector/executions/{execution_id}/tree",
            service="admin.v1.inspector.executions.tree",
            description="Inspector: execution retry tree",
        ))
        # Schedules inspector
        self.runtime.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/inspector/schedules",
            service="admin.v1.inspector.schedules",
            description="Inspector: list execution schedules",
        ))
        self.runtime.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/inspector/schedules/{schedule_id}",
            service="admin.v1.inspector.schedules.get",
            description="Inspector: get execution schedule by id",
        ))
        self.runtime.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/inspector/operations/{operation_id}/schedules",
            service="admin.v1.inspector.operations.schedules",
            description="Inspector: list schedules for operation",
        ))

        # --- Webhook demo (C4) ---
        async def webhook_test_service(payload, **kwargs):
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"[C4 Webhook Demo] Received payload: {payload}")
            return {
                "ok": True,
                "message": "Webhook received and processed",
                "payload_type": str(type(payload).__name__),
                "payload_sample": str(payload)[:100] if payload else None
            }
        await self.runtime.service_registry.register("system.webhook_test", webhook_test_service)

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
                eid = execution_id if execution_id is not None else kw.get("execution_id") or kw.get("id")
                return await get_execution_trace(self.runtime, eid)

            return handler

        def wrap_operation_executions():
            async def handler(operation_id=None, **kw):
                oid = operation_id if operation_id is not None else kw.get("operation_id") or kw.get("id")
                return await list_operation_executions(self.runtime, oid)

            return handler

        def wrap_execution_retries():
            async def handler(execution_id=None, **kw):
                eid = execution_id if execution_id is not None else kw.get("execution_id") or kw.get("id")
                return await list_execution_retries(self.runtime, eid)

            return handler

        def wrap_execution_tree():
            async def handler(execution_id=None, **kw):
                eid = execution_id if execution_id is not None else kw.get("execution_id") or kw.get("id")
                return await get_execution_tree(self.runtime, eid)

            return handler

        def wrap_schedules():
            return lambda *args, **kw: list_schedules(self.runtime)

        def wrap_schedule_get():
            async def handler(schedule_id=None, **kw):
                sid = schedule_id if schedule_id is not None else kw.get("schedule_id") or kw.get("id")
                return await get_schedule(self.runtime, sid)

            return handler

        def wrap_operation_schedules():
            async def handler(operation_id=None, **kw):
                oid = operation_id if operation_id is not None else kw.get("operation_id") or kw.get("id")
                return await list_operation_schedules(self.runtime, oid)

            return handler

        registrations = [
            ("admin.v1.runtime", wrap_introspection(get_runtime_info, with_started_at=True)),
            ("admin.v1.plugins", wrap_introspection(list_plugins)),
            ("admin.v1.services", wrap_introspection(list_services)),
            ("admin.v1.http", wrap_introspection(list_http_endpoints)),
            ("admin.v1.events", wrap_introspection(list_events)),
            ("admin.v1.storage", wrap_introspection(list_storage_namespaces)),
            ("admin.v1.state", wrap_introspection(get_state)),
            ("admin.v1.state.keys", wrap_introspection(list_state_keys)),
            ("admin.v1.state.get", wrap_state_get()),
            ("admin.v1.inspector.operations", wrap_introspection(list_operations_available)),
            ("admin.v1.inspector.auth", wrap_introspection(list_auth_flows)),
            ("admin.v1.inspector.integrations", wrap_introspection(list_integrations)),
            ("admin.v1.inspector.inventory", wrap_introspection(lambda runtime: [])),
            ("admin.v1.inspector.capabilities", wrap_introspection(list_capabilities)),
            ("admin.v1.inspector.executions", wrap_introspection(list_execution_traces)),
            ("admin.v1.inspector.executions.get", wrap_execution_get()),
            ("admin.v1.inspector.operations.executions", wrap_operation_executions()),
            ("admin.v1.inspector.executions.retries", wrap_execution_retries()),
            ("admin.v1.inspector.executions.tree", wrap_execution_tree()),
            ("admin.v1.inspector.schedules", wrap_schedules()),
            ("admin.v1.inspector.schedules.get", wrap_schedule_get()),
            ("admin.v1.inspector.operations.schedules", wrap_operation_schedules()),
            ("admin.v1.inspector.auth", wrap_introspection(inspector_auth_summary)),
            # Admin devices read-only proxy services (kept for Admin UI compatibility)
            ("admin.v1.devices.list", wrap_domain(__import__("modules.admin.devices", fromlist=["admin_devices_list"]).admin_devices_list)),
            ("admin.v1.devices.get", wrap_domain(__import__("modules.admin.devices", fromlist=["admin_devices_get"]).admin_devices_get)),
            ("admin.v1.devices.list_external", wrap_domain(__import__("modules.admin.devices", fromlist=["admin_devices_list_external"]).admin_devices_list_external)),
            ("admin.v1.devices.list_mappings", wrap_domain(__import__("modules.admin.devices", fromlist=["admin_devices_list_mappings"]).admin_devices_list_mappings)),
            ("admin.operations.create", wrap_domain(admin_operations_create)),
            ("admin.operations.list", wrap_domain(admin_operations_list)),
            ("admin.operations.get", wrap_domain(admin_operations_get)),
            ("admin.operations.cancel", wrap_domain(admin_operations_cancel)),
            ("admin.operations.retry", wrap_domain(admin_operations_retry)),
            ("admin.auth.create_api_key", wrap_domain(admin_auth_create_api_key)),
            ("admin.auth.list_api_keys", wrap_domain(admin_auth_list_api_keys)),
            ("admin.auth.create_user", wrap_domain(admin_auth_create_user)),
            ("admin.auth.list_users", wrap_domain(admin_auth_list_users)),
            ("admin.auth.initialize", wrap_domain(admin_auth_initialize)),
            ("admin.auth.login", wrap_domain(admin_auth_login)),
            ("admin.auth.refresh", wrap_domain(admin_auth_refresh)),
            ("admin.auth.set_password", wrap_domain(admin_auth_set_password)),
            ("admin.auth.change_password", wrap_domain(admin_auth_change_password)),
            ("admin.auth.list_sessions", wrap_domain(admin_auth_list_sessions)),
            ("admin.auth.revoke_session", wrap_domain(admin_auth_revoke_session)),
            ("admin.auth.revoke_all_sessions", wrap_domain(admin_auth_revoke_all_sessions)),
            ("admin.auth.revoke_api_key", wrap_domain(admin_auth_revoke_api_key)),
            ("admin.auth.rotate_api_key", wrap_domain(admin_auth_rotate_api_key)),
            ("admin.auth.me", wrap_domain(admin_auth_me)),
        ]

        public_auth_services = {"admin.auth.initialize", "admin.auth.login", "admin.auth.refresh", "admin.auth.me"}
        for name, handler in registrations:
            try:
                # Allow internal calls to inspector/admin.v1.* services without admin ctx
                if name.startswith("admin.v1."):
                    admin_only = False
                else:
                    admin_only = name not in public_auth_services
                if hasattr(self.runtime.service_registry, "register_with_acl"):
                    await self.runtime.service_registry.register_with_acl(name, handler, admin_only=admin_only)
                else:
                    await self.runtime.service_registry.register(name, handler)
                self._registered_services.append(name)
            except ValueError:
                continue

        # --- Plugin control: unload / reload (admin-only) ---
        async def _admin_unload_plugin(plugin_name: str, **kw):
            try:
                await self.runtime.plugin_manager.unload_plugin(plugin_name)
                return {"ok": True}
            except Exception as e:
                return {"ok": False, "error": str(e)}

        async def _admin_reload_plugin(plugin_name: str, **kw):
            try:
                await self.runtime.plugin_manager.reload_plugin(plugin_name)
                return {"ok": True}
            except Exception as e:
                return {"ok": False, "error": str(e)}

        try:
            # Register services (admin-only)
            if hasattr(self.runtime.service_registry, "register_with_acl"):
                await self.runtime.service_registry.register_with_acl("admin.v1.plugins.unload", _admin_unload_plugin, admin_only=True)
                await self.runtime.service_registry.register_with_acl("admin.v1.plugins.reload", _admin_reload_plugin, admin_only=True)
            else:
                await self.runtime.service_registry.register("admin.v1.plugins.unload", _admin_unload_plugin)
                await self.runtime.service_registry.register("admin.v1.plugins.reload", _admin_reload_plugin)
            self._registered_services.extend(["admin.v1.plugins.unload", "admin.v1.plugins.reload"])
        except Exception:
            # Best-effort: do not break admin registration
            pass

        # Expose HTTP endpoints for plugin control
        try:
            self.runtime.http.register(HttpEndpoint(
                method="POST",
                path="/admin/v1/plugins/{name}/unload",
                service="admin.v1.plugins.unload",
                description="Unload plugin by name (admin only)"
            ))
            self.runtime.http.register(HttpEndpoint(
                method="POST",
                path="/admin/v1/plugins/{name}/reload",
                service="admin.v1.plugins.reload",
                description="Reload plugin by name (admin only)"
            ))
        except Exception:
            pass

        # HTTP endpoints for admin devices (read-only + set_state proxy)
        try:
            self.runtime.http.register(HttpEndpoint(
                method="GET",
                path="/admin/v1/devices",
                service="admin.v1.devices.list",
                description="List internal devices"
            ))
            self.runtime.http.register(HttpEndpoint(
                method="GET",
                path="/admin/v1/devices/{id}",
                service="admin.v1.devices.get",
                description="Get device by id"
            ))
            self.runtime.http.register(HttpEndpoint(
                method="GET",
                path="/admin/v1/devices/external/{provider}",
                service="admin.v1.devices.list_external",
                description="List external devices by provider"
            ))
            self.runtime.http.register(HttpEndpoint(
                method="GET",
                path="/admin/v1/devices/mappings",
                service="admin.v1.devices.list_mappings",
                description="List device mappings"
            ))
            # POST to set device state — proxy to devices.set_state (domain service)
            async def _admin_set_state(device_id: str, body: dict = None, **kw):
                from core.system_context import create_system_context
                from core.auth_contextvars import set_current_auth_context, get_current_auth_context
                ctx = create_system_context("admin", "devices.set_state")
                prev = get_current_auth_context()
                try:
                    # Normalize common admin payloads (e.g., {"power":"on"} -> desired.on = True)
                    payload = body
                    if isinstance(body, dict) and "power" in body:
                        payload = {"state": {"on": True if body.get("power") == "on" else False}}
                    set_current_auth_context(ctx)
                    return await self.runtime.service_registry.call("devices.set_state", device_id, payload)
                finally:
                    set_current_auth_context(prev)

            await self.runtime.service_registry.register("admin.v1.devices.set_state", _admin_set_state)
            self.runtime.http.register(HttpEndpoint(
                method="POST",
                path="/admin/v1/devices/{id}/state",
                service="admin.v1.devices.set_state",
                description="Set device desired state (proxy to devices.set_state)"
            ))
        except Exception:
            # Best-effort: do not break admin registration if HTTP registry unavailable
            pass

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        for service_name in self._registered_services:
            try:
                await self.runtime.service_registry.unregister(service_name)
            except Exception:
                pass
        self._registered_services.clear()
