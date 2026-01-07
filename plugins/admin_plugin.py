"""
Admin plugin — простые HTTP-ручки и сервисы для администрирования/отладки.

Экспонирует:
- сервисы: `admin.list_plugins`, `admin.list_services`, `admin.list_http`,
  `admin.state_keys`, `admin.state_get`
- HTTP: GET /admin/plugins, GET /admin/services, GET /admin/http,
  GET /admin/state/keys, GET /admin/state/{key}

Этот плагин безопасен для dev окружения — не даёт возможности менять состояние,
только читать. В production при необходимости добавить аутентификацию.
"""
from typing import Any, Dict, List, Optional

from plugins.base_plugin import BasePlugin, PluginMetadata


class AdminPlugin(BasePlugin):
    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="admin",
            version="0.1.0",
            description="Admin endpoints for runtime inspection",
            author="Home Console",
        )

    async def on_load(self) -> None:
        await super().on_load()

        async def list_plugins() -> List[str]:
            return self.runtime.plugin_manager.list_plugins()

        async def list_services() -> List[str]:
            return self.runtime.service_registry.list_services()

        async def list_http() -> List[Dict[str, Any]]:
            return [
                {"method": ep.method, "path": ep.path, "service": ep.service, "description": ep.description}
                for ep in self.runtime.http.list()
            ]

        async def state_keys() -> List[str]:
            return await self.runtime.state_engine.keys()

        async def state_get(key: str) -> Optional[Any]:
            return await self.runtime.state_engine.get(key)

        # Register services
        self.runtime.service_registry.register("admin.list_plugins", list_plugins)
        self.runtime.service_registry.register("admin.list_services", list_services)
        self.runtime.service_registry.register("admin.list_http", list_http)
        self.runtime.service_registry.register("admin.state_keys", state_keys)
        self.runtime.service_registry.register("admin.state_get", state_get)

        # Register HTTP endpoints
        from core.http_registry import HttpEndpoint

        try:
            self.runtime.http.register(HttpEndpoint(
                method="GET",
                path="/admin/plugins",
                service="admin.list_plugins",
                description="List loaded plugins"
            ))
            self.runtime.http.register(HttpEndpoint(
                method="GET",
                path="/admin/services",
                service="admin.list_services",
                description="List registered services"
            ))
            self.runtime.http.register(HttpEndpoint(
                method="GET",
                path="/admin/http",
                service="admin.list_http",
                description="List HTTP endpoints"
            ))
            self.runtime.http.register(HttpEndpoint(
                method="GET",
                path="/admin/state/keys",
                service="admin.state_keys",
                description="List state keys"
            ))
            self.runtime.http.register(HttpEndpoint(
                method="GET",
                path="/admin/state/{key}",
                service="admin.state_get",
                description="Get state value by key"
            ))
        except Exception:
            # Не критично — не блокируем загрузку
            pass

    async def on_unload(self) -> None:
        await super().on_unload()
        try:
            self.runtime.service_registry.unregister("admin.list_plugins")
            self.runtime.service_registry.unregister("admin.list_services")
            self.runtime.service_registry.unregister("admin.list_http")
            self.runtime.service_registry.unregister("admin.state_keys")
            self.runtime.service_registry.unregister("admin.state_get")
        except Exception:
            pass
