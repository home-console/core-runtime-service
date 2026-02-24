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
import asyncio
import json
import logging
import shutil
import time

from core.runtime_module import RuntimeModule
from core.http_registry import HttpEndpoint
from .container_orchestrator import ContainerOrchestrator

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
)
from .introspection import (
    get_runtime_info,
    list_plugins,
    list_services,
    list_http_endpoints,
    list_events,
    list_storage_namespaces,
    get_storage_namespace_contents,
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
from modules.agents.agent_deploy_service import admin_agent_deploy
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
        self._container_orchestrator = ContainerOrchestrator()

    async def register(self) -> None:
        self._admin_started_at = time.time()
        self._registered_services = []

        # --- HTTP: Inspector (read-only snapshot) ---
        inspector_endpoints = [
            ("/admin/v1/inspector/dashboard", "admin.v1.inspector.dashboard", "Inspector: dashboard summary"),
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
            self.context.http.register(HttpEndpoint(
                method="GET",
                path=path,
                service=service,
                description=description
            ))
        # Плагины: discovery и детали одного (из ядра) — регистрируем до /plugins/{name}
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/inspector/plugins/discover",
            service="admin.v1.inspector.plugins.discover",
            description="Inspector: discover plugins on disk (manifests, load_order)"
        ))
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/inspector/plugins/{name}",
            service="admin.v1.inspector.plugins.get",
            description="Inspector: get single plugin details (loaded + manifest)"
        ))
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/marketplace/catalog",
            service="admin.v1.marketplace.catalog",
            description="Marketplace: список плагинов (один файл catalog.json, ссылки на репо)"
        ))
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/inspector/state/{key}",
            service="admin.v1.state.get",
            description="Inspector: get state value by key"
        ))
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/inspector/storage/{namespace}",
            service="admin.v1.storage.get",
            description="Inspector: get storage namespace contents (keys + values)"
        ))
        # Credentials (SSH hosts, etc.) — admin API
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/credentials",
            service="admin.v1.credentials.list",
            description="Admin: list credentials"
        ))
        self.context.http.register(HttpEndpoint(
            method="POST",
            path="/admin/v1/credentials",
            service="admin.v1.credentials.create",
            description="Admin: create credential"
        ))
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/credentials/{credential_id}",
            service="admin.v1.credentials.get",
            description="Admin: get credential by id"
        ))
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/credentials/{credential_id}/secret",
            service="admin.v1.credentials.get_secret",
            description="Admin: get credential secret (for export)"
        ))
        self.context.http.register(HttpEndpoint(
            method="PUT",
            path="/admin/v1/credentials/{credential_id}",
            service="admin.v1.credentials.update",
            description="Admin: update credential"
        ))
        self.context.http.register(HttpEndpoint(
            method="DELETE",
            path="/admin/v1/credentials/{credential_id}",
            service="admin.v1.credentials.delete",
            description="Admin: delete credential"
        ))
        self.context.http.register(HttpEndpoint(
            method="POST",
            path="/admin/v1/credentials/{credential_id}/connect",
            service="admin.v1.credentials.connect",
            description="Admin: подключиться к хосту по креду из БД (SSH)"
        ))
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/credentials/terminal-sessions",
            service="admin.v1.credentials.terminal_sessions",
            description="Admin: список активных SSH терминальных сессий"
        ))
        self.context.http.register(HttpEndpoint(
            path="/admin/v1/credentials/terminal",
            service="admin.v1.credentials.terminal_ws",
            websocket=True,
            description="Admin: WebSocket терминал по креду (?credential_id=...)"
        ))
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/inspector/executions/{execution_id}",
            service="admin.v1.inspector.executions.get",
            description="Inspector: get execution trace by id",
        ))
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/inspector/operations/{operation_id}/executions",
            service="admin.v1.inspector.operations.executions",
            description="Inspector: list executions for operation",
        ))
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/inspector/executions/{execution_id}/retries",
            service="admin.v1.inspector.executions.retries",
            description="Inspector: list retries for execution",
        ))
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/inspector/executions/{execution_id}/tree",
            service="admin.v1.inspector.executions.tree",
            description="Inspector: execution retry tree",
        ))
        # Schedules inspector
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/inspector/schedules",
            service="admin.v1.inspector.schedules",
            description="Inspector: list execution schedules",
        ))
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/inspector/schedules/{schedule_id}",
            service="admin.v1.inspector.schedules.get",
            description="Inspector: get execution schedule by id",
        ))
        self.context.http.register(HttpEndpoint(
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
                return await admin_credentials_get_secret(self.runtime, credential_id=cid)
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
                return await admin_credentials_update(self.runtime, credential_id=cid, body=b)
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

        def wrap_agent_deploy():
            async def handler(body=None, **kw):
                b = body if body is not None else kw.get("body")
                return await admin_agent_deploy(self.runtime, b)
            return handler

        async def _marketplace_catalog(*args, **kw):
            """Список плагинов для маркетплейса: один захардкоженный файл catalog.json (ссылки на репо)."""
            catalog_path = Path(__file__).resolve().parent.parent / "marketplace" / "catalog.json"
            try:
                if catalog_path.exists():
                    data = json.loads(catalog_path.read_text(encoding="utf-8"))
                    return {"catalog": data if isinstance(data, list) else []}
            except Exception as e:
                logger.warning("marketplace catalog read failed: %s", e)
            return {"catalog": []}

        registrations = [
            ("admin.v1.runtime", wrap_introspection(get_runtime_info, with_started_at=True)),
            ("admin.v1.plugins", wrap_introspection(list_plugins)),
            ("admin.v1.inspector.plugins.discover", wrap_introspection(discover_manifests_for_inspector)),
            ("admin.v1.inspector.plugins.get", wrap_plugin_get()),
            ("admin.v1.services", wrap_introspection(list_services)),
            ("admin.v1.http", wrap_introspection(list_http_endpoints)),
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
            ("admin.v1.credentials.terminal_sessions", wrap_credentials_terminal_sessions()),
            ("admin.v1.state", wrap_introspection(get_state)),
            ("admin.v1.state.keys", wrap_introspection(list_state_keys)),
            ("admin.v1.state.get", wrap_state_get()),
            ("admin.v1.inspector.operations", wrap_introspection(list_operations_available)),
            ("admin.v1.inspector.auth", wrap_introspection(list_auth_flows)),
            ("admin.v1.inspector.integrations", wrap_introspection(integrations_inspector_response)),
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
            ("admin.v1.inspector.dashboard", wrap_introspection(dashboard_inspector_response)),
            ("admin.v1.marketplace.catalog", _marketplace_catalog),
            # Admin devices read-only proxy services (kept for Admin UI compatibility)
            ("admin.v1.devices.list", wrap_domain(__import__("modules.admin.devices", fromlist=["admin_devices_list"]).admin_devices_list)),
            ("admin.v1.devices.get", wrap_domain(__import__("modules.admin.devices", fromlist=["admin_devices_get"]).admin_devices_get)),
            ("admin.v1.devices.list_external", wrap_domain(__import__("modules.admin.devices", fromlist=["admin_devices_list_external"]).admin_devices_list_external)),
            ("admin.v1.devices.list_mappings", wrap_domain(__import__("modules.admin.devices", fromlist=["admin_devices_list_mappings"]).admin_devices_list_mappings)),
            ("admin.v1.devices.get_external_for_device", wrap_domain(__import__("modules.admin.devices", fromlist=["admin_devices_get_external_for_device"]).admin_devices_get_external_for_device)),
            ("admin.operations.create", wrap_domain(admin_operations_create)),
            ("admin.operations.list", wrap_domain(admin_operations_list)),
            ("admin.operations.get", wrap_domain(admin_operations_get)),
            ("admin.operations.cancel", wrap_domain(admin_operations_cancel)),
            ("admin.operations.retry", wrap_domain(admin_operations_retry)),
            ("admin.agents.deploy", wrap_agent_deploy()),
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
                services = self.context.services
                if hasattr(services, "register_with_acl"):
                    await services.register_with_acl(name, handler, admin_only=admin_only)
                else:
                    await services.register(name, handler)
                self._registered_services.append(name)
            except ValueError:
                continue

        # --- Plugin control: unload / reload / restart container (admin-only) ---
        async def _admin_unload_plugin(name: str = None, **kw):
            """
            Выгрузить плагин.
            
            Args:
                name: имя плагина (из URL path параметра {name})
            """
            plugin_name = name or kw.get("name")
            if not plugin_name:
                return {"ok": False, "error": "Имя плагина не указано"}
            try:
                await self.runtime.plugin_manager.unload_plugin(plugin_name)
                return {"ok": True}
            except Exception as e:
                return {"ok": False, "error": str(e)}

        async def _admin_reload_plugin(name: str = None, **kw):
            """
            Перезагрузить плагин (hot-reload).
            
            Args:
                name: имя плагина (из URL path параметра {name})
            """
            plugin_name = name or kw.get("name")
            if not plugin_name:
                return {"ok": False, "error": "Имя плагина не указано"}
            try:
                await self.runtime.plugin_manager.reload_plugin(plugin_name)
                return {"ok": True}
            except Exception as e:
                return {"ok": False, "error": str(e)}

        async def _admin_restart_plugin_container(name: str = None, body: Any = None, **kw):
            """
            Перезапустить плагин через перезапуск Docker контейнера.
            
            Если контейнер не существует, автоматически вызывает ensure_container для создания.
            Архитектурное разделение: restart использует ContainerOrchestrator для DevOps операций.
            
            Args:
                name: имя плагина (из URL path параметра {name})
                body: тело запроса (может содержать container_name)
            
            Returns:
                {"ok": True} при успехе, {"ok": False, "error": "..."} при ошибке
            """
            plugin_name = name or kw.get("name")
            if not plugin_name:
                return {"ok": False, "error": "Имя плагина не указано"}
            
            # Получаем плагин
            plugin = self.runtime.plugin_manager.get_plugin(plugin_name)
            if not plugin:
                return {"ok": False, "error": f"Плагин '{plugin_name}' не найден"}
            
            # Проверяем, что плагин настроен на container mode
            metadata = plugin.metadata
            if metadata.execution_mode != "container":
                return {
                    "ok": False,
                    "error": f"Плагин '{plugin_name}' не является container плагином (execution_mode: {metadata.execution_mode}). "
                            f"Используйте reload для перезапуска."
                }
            
            if not metadata.container_config:
                return {
                    "ok": False,
                    "error": f"У плагина '{plugin_name}' не указан container_config в metadata"
                }
            
            # Определяем имя контейнера из metadata или body
            container_name = None
            if isinstance(body, dict):
                container_name = body.get("container_name")
            
            if not container_name:
                container_name = metadata.container_config.get("name")
            
            if not container_name:
                container_name = f"plugin-{plugin_name}"
            
            # Проверяем наличие docker
            docker_cmd = shutil.which("docker")
            if not docker_cmd:
                return {"ok": False, "error": "Docker не найден в системе"}
            
            # Проверяем существование контейнера
            container_exists = await self._container_orchestrator.container_exists(container_name)
            
            # Если контейнер не существует, пытаемся создать его
            if not container_exists:
                logger.info(f"Container {container_name} not found, attempting to ensure it exists")
                ensure_result = await self._container_orchestrator.ensure_container(
                    container_name,
                    metadata.container_config
                )
                if not ensure_result["ok"]:
                    return ensure_result
                # После создания контейнера продолжаем с restart
            
            # Выполняем docker restart
            try:
                logger.info(f"Restarting container {container_name} for plugin {plugin_name}")
                proc = await asyncio.create_subprocess_exec(
                    docker_cmd,
                    "restart",
                    container_name,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
                
                if proc.returncode == 0:
                    logger.info(f"Container {container_name} restarted successfully")
                    return {"ok": True, "message": f"Контейнер {container_name} успешно перезапущен"}
                else:
                    error_msg = stderr.decode("utf-8", errors="replace") if stderr else "Неизвестная ошибка"
                    logger.warning(f"Failed to restart container {container_name}: {error_msg}")
                    
                    # Если ошибка связана с сетью, удаляем контейнер и пересоздаём
                    if "network" in error_msg.lower() and "not found" in error_msg.lower():
                        logger.info(f"Network error detected, removing container {container_name} to recreate it")
                        remove_result = await self._container_orchestrator.remove_container(container_name, force=True)
                        if remove_result["ok"]:
                            # Пересоздаём контейнер с правильной сетью
                            logger.info(f"Recreating container {container_name} with correct network configuration")
                            ensure_result = await self._container_orchestrator.ensure_container(
                                container_name,
                                metadata.container_config
                            )
                            if ensure_result["ok"]:
                                return {"ok": True, "message": f"Контейнер '{container_name}' пересоздан и запущен (была проблема с сетью)"}
                            else:
                                return ensure_result
                        else:
                            return {
                                "ok": False,
                                "error": f"Не удалось перезапустить контейнер '{container_name}': {error_msg}. "
                                        f"Также не удалось удалить контейнер для пересоздания: {remove_result.get('error', 'неизвестная ошибка')}"
                            }
                    
                    return {
                        "ok": False,
                        "error": f"Не удалось перезапустить контейнер '{container_name}': {error_msg}"
                    }
            except asyncio.TimeoutError:
                logger.error(f"Timeout while restarting container {container_name}")
                return {"ok": False, "error": "Таймаут при перезапуске контейнера"}
            except Exception as e:
                logger.exception(f"Error restarting container {container_name} for plugin {plugin_name}")
                return {"ok": False, "error": str(e)}

        async def _admin_ensure_plugin_container(name: str = None, body: Any = None, **kw):
            """
            Убедиться, что контейнер плагина существует и запущен.
            
            Если контейнер не существует:
            - Проверяет наличие образа
            - Если образа нет и указан build в container_config — собирает образ
            - Создаёт и запускает контейнер
            
            Использует ContainerOrchestrator для DevOps-операций (сборка, создание).
            Runtime остаётся чистым — только управление существующими контейнерами.
            
            Args:
                name: имя плагина (из URL path параметра {name})
                body: тело запроса (может содержать container_name)
            
            Returns:
                {"ok": True} при успехе, {"ok": False, "error": "..."} при ошибке
            """
            plugin_name = name or kw.get("name")
            if not plugin_name:
                return {"ok": False, "error": "Имя плагина не указано"}
            
            # Получаем плагин
            plugin = self.runtime.plugin_manager.get_plugin(plugin_name)
            if not plugin:
                return {"ok": False, "error": f"Плагин '{plugin_name}' не найден"}
            
            # Проверяем, что плагин настроен на container mode
            metadata = plugin.metadata
            if metadata.execution_mode != "container":
                return {
                    "ok": False,
                    "error": f"Плагин '{plugin_name}' не является container плагином (execution_mode: {metadata.execution_mode}). "
                            f"Используйте reload для перезапуска."
                }
            
            if not metadata.container_config:
                return {
                    "ok": False,
                    "error": f"У плагина '{plugin_name}' не указан container_config в metadata"
                }
            
            # Определяем имя контейнера из metadata или body
            container_name = None
            if isinstance(body, dict):
                container_name = body.get("container_name")
            
            if not container_name:
                container_name = metadata.container_config.get("name")
            
            if not container_name:
                container_name = f"plugin-{plugin_name}"
            
            # Используем ContainerOrchestrator для обеспечения существования контейнера
            return await self._container_orchestrator.ensure_container(
                container_name,
                metadata.container_config
            )

        async def _admin_start_plugin(name: str = None, **kw):
            """Запустить плагин (ядро: plugin_manager.start_plugin)."""
            plugin_name = name or kw.get("name")
            if not plugin_name:
                return {"ok": False, "error": "Имя плагина не указано"}
            try:
                await self.runtime.plugin_manager.start_plugin(plugin_name)
                return {"ok": True}
            except Exception as e:
                return {"ok": False, "error": str(e)}

        async def _admin_stop_plugin(name: str = None, **kw):
            """Остановить плагин (ядро: plugin_manager.stop_plugin)."""
            plugin_name = name or kw.get("name")
            if not plugin_name:
                return {"ok": False, "error": "Имя плагина не указано"}
            try:
                await self.runtime.plugin_manager.stop_plugin(plugin_name)
                return {"ok": True}
            except Exception as e:
                return {"ok": False, "error": str(e)}

        async def _admin_load_plugin_by_name(name: str = None, body: Any = None, **kw):
            """Загрузить один плагин по имени из каталога (ядро: plugin_manager.load_plugin_by_name)."""
            plugin_name = name or (isinstance(body, dict) and body.get("name")) or kw.get("name")
            if not plugin_name:
                return {"ok": False, "error": "Имя плагина не указано"}
            try:
                plugins_dir = None
                if isinstance(body, dict) and body.get("plugins_dir"):
                    plugins_dir = Path(body["plugins_dir"])
                ok = await self.runtime.plugin_manager.load_plugin_by_name(plugin_name, plugins_dir=plugins_dir)
                if ok:
                    return {"ok": True}
                return {"ok": False, "error": f"Не удалось загрузить плагин '{plugin_name}' (нет манифеста или зависимости)"}
            except Exception as e:
                return {"ok": False, "error": str(e)}

        async def _admin_auto_load_plugins(body: Any = None, **kw):
            """Пересканировать каталог и загрузить плагины по манифестам (ядро: plugin_manager.auto_load_plugins)."""
            plugins_dir = None
            if isinstance(body, dict) and body.get("plugins_dir"):
                plugins_dir = Path(body["plugins_dir"])
            try:
                await self.runtime.plugin_manager.auto_load_plugins(plugins_dir=plugins_dir)
                return {"ok": True, "loaded": self.runtime.plugin_manager.list_plugins()}
            except Exception as e:
                return {"ok": False, "error": str(e)}

        try:
            # Register services (admin-only)
            services = self.context.services
            if hasattr(services, "register_with_acl"):
                await services.register_with_acl("admin.v1.plugins.unload", _admin_unload_plugin, admin_only=True)
                await services.register_with_acl("admin.v1.plugins.reload", _admin_reload_plugin, admin_only=True)
                await services.register_with_acl("admin.v1.plugins.restart_container", _admin_restart_plugin_container, admin_only=True)
                await services.register_with_acl("admin.v1.plugins.ensure_container", _admin_ensure_plugin_container, admin_only=True)
                await services.register_with_acl("admin.v1.plugins.start", _admin_start_plugin, admin_only=True)
                await services.register_with_acl("admin.v1.plugins.stop", _admin_stop_plugin, admin_only=True)
                await services.register_with_acl("admin.v1.plugins.load_by_name", _admin_load_plugin_by_name, admin_only=True)
                await services.register_with_acl("admin.v1.plugins.auto_load", _admin_auto_load_plugins, admin_only=True)
            else:
                await services.register("admin.v1.plugins.unload", _admin_unload_plugin)
                await services.register("admin.v1.plugins.reload", _admin_reload_plugin)
                await services.register("admin.v1.plugins.restart_container", _admin_restart_plugin_container)
                await services.register("admin.v1.plugins.ensure_container", _admin_ensure_plugin_container)
                await services.register("admin.v1.plugins.start", _admin_start_plugin)
                await services.register("admin.v1.plugins.stop", _admin_stop_plugin)
                await services.register("admin.v1.plugins.load_by_name", _admin_load_plugin_by_name)
                await services.register("admin.v1.plugins.auto_load", _admin_auto_load_plugins)
            self._registered_services.extend([
                "admin.v1.plugins.unload", "admin.v1.plugins.reload", "admin.v1.plugins.restart_container",
                "admin.v1.plugins.ensure_container", "admin.v1.plugins.start", "admin.v1.plugins.stop",
                "admin.v1.plugins.load_by_name", "admin.v1.plugins.auto_load",
            ])
        except Exception:
            # Best-effort: do not break admin registration
            pass

        # Expose HTTP endpoints for plugin control
        try:
            self.context.http.register(HttpEndpoint(
                method="POST",
                path="/admin/v1/plugins/{name}/unload",
                service="admin.v1.plugins.unload",
                description="Unload plugin by name (admin only)"
            ))
            self.context.http.register(HttpEndpoint(
                method="POST",
                path="/admin/v1/plugins/{name}/reload",
                service="admin.v1.plugins.reload",
                description="Reload plugin by name (admin only)"
            ))
            self.context.http.register(HttpEndpoint(
                method="POST",
                path="/admin/v1/plugins/{name}/restart-container",
                service="admin.v1.plugins.restart_container",
                description="Restart plugin container by name (admin only)"
            ))
            self.context.http.register(HttpEndpoint(
                method="POST",
                path="/admin/v1/plugins/{name}/ensure-container",
                service="admin.v1.plugins.ensure_container",
                description="Ensure plugin container exists (build and create if needed, admin only)"
            ))
            self.context.http.register(HttpEndpoint(
                method="POST",
                path="/admin/v1/plugins/{name}/start",
                service="admin.v1.plugins.start",
                description="Start plugin by name (kernel: plugin_manager.start_plugin)"
            ))
            self.context.http.register(HttpEndpoint(
                method="POST",
                path="/admin/v1/plugins/{name}/stop",
                service="admin.v1.plugins.stop",
                description="Stop plugin by name (kernel: plugin_manager.stop_plugin)"
            ))
            self.context.http.register(HttpEndpoint(
                method="POST",
                path="/admin/v1/plugins/load",
                service="admin.v1.plugins.load_by_name",
                description="Load one plugin by name from plugins dir (kernel: load_plugin_by_name). Body: { name?, plugins_dir? }"
            ))
            self.context.http.register(HttpEndpoint(
                method="POST",
                path="/admin/v1/plugins/{name}/load",
                service="admin.v1.plugins.load_by_name",
                description="Load one plugin by name from path (kernel: load_plugin_by_name)"
            ))
            self.context.http.register(HttpEndpoint(
                method="POST",
                path="/admin/v1/plugins/auto-load",
                service="admin.v1.plugins.auto_load",
                description="Rescan plugins dir and load from manifests (kernel: auto_load_plugins). Body: { plugins_dir? }"
            ))
        except Exception:
            pass

        # HTTP endpoints for admin devices (read-only + set_state proxy)
        try:
            self.context.http.register(HttpEndpoint(
                method="GET",
                path="/admin/v1/devices",
                service="admin.v1.devices.list",
                description="List internal devices"
            ))
            self.context.http.register(HttpEndpoint(
                method="GET",
                path="/admin/v1/devices/{id}",
                service="admin.v1.devices.get",
                description="Get device by id"
            ))
            self.context.http.register(HttpEndpoint(
                method="GET",
                path="/admin/v1/devices/external/{provider}",
                service="admin.v1.devices.list_external",
                description="List external devices by provider"
            ))
            self.context.http.register(HttpEndpoint(
                method="GET",
                path="/admin/v1/devices/external",
                service="admin.v1.devices.list_external",
                description="List all external devices (optional ?provider=yandex to filter)"
            ))
            self.context.http.register(HttpEndpoint(
                method="GET",
                path="/admin/v1/devices/mappings",
                service="admin.v1.devices.list_mappings",
                description="List device mappings"
            ))
            self.context.http.register(HttpEndpoint(
                method="GET",
                path="/admin/v1/devices/{id}/external",
                service="admin.v1.devices.get_external_for_device",
                description="Get external device payload (Yandex etc.) for an internal device"
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
                    return await self.context.services.call("devices.set_state", device_id, payload)
                finally:
                    set_current_auth_context(prev)

            await self.context.services.register("admin.v1.devices.set_state", _admin_set_state)
            self.context.http.register(HttpEndpoint(
                method="POST",
                path="/admin/v1/devices/{id}/state",
                service="admin.v1.devices.set_state",
                description="Set device desired state (proxy to devices.set_state)"
            ))
        except Exception:
            # Best-effort: do not break admin registration if HTTP registry unavailable
            pass

        # HTTP endpoint для SSH‑деплоя агентов (admin‑only через ACL)
        try:
            self.context.http.register(HttpEndpoint(
                method="POST",
                path="/admin/v1/agents/deploy",
                service="admin.agents.deploy",
                description="Deploy agent over SSH using existing credentials (admin only)",
            ))
        except Exception:
            pass

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        for service_name in self._registered_services:
            try:
                await self.context.services.unregister(service_name)
            except Exception:
                pass
        self._registered_services.clear()
