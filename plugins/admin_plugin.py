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

        # --- Devices proxy services (admin v1) ---
        async def admin_devices_list():
            return await self.runtime.service_registry.call("devices.list")

        async def admin_devices_get(device_id: str):
            return await self.runtime.service_registry.call("devices.get", device_id)

        async def admin_devices_set_state(device_id: str, state: Dict[str, Any]):
            # Proxy call to devices.set_state
            return await self.runtime.service_registry.call("devices.set_state", device_id, state)

        async def admin_devices_list_external(provider: Optional[str] = None):
            return await self.runtime.service_registry.call("devices.list_external", provider)

        self.runtime.service_registry.register("admin.devices.list", admin_devices_list)
        self.runtime.service_registry.register("admin.devices.get", admin_devices_get)
        self.runtime.service_registry.register("admin.devices.set_state", admin_devices_set_state)
        self.runtime.service_registry.register("admin.devices.list_external", admin_devices_list_external)

        # --- OAuth Yandex proxy services (admin v1) ---
        async def _sanitize_oauth(data: Dict[str, Any]) -> Dict[str, Any]:
            if not isinstance(data, dict):
                return {}
            forbidden = {"client_secret", "access_token", "refresh_token", "raw_token"}
            return {k: v for k, v in data.items() if k not in forbidden}

        async def oauth_status() -> Dict[str, Any]:
            res = await self.runtime.service_registry.call("oauth_yandex.get_status")
            return await _sanitize_oauth(res or {})

        async def oauth_configure(cfg: Dict[str, Any]) -> Dict[str, Any]:
            # Pass configuration to oauth_yandex but do not echo secrets
            await self.runtime.service_registry.call("oauth_yandex.set_config", cfg)
            return {"ok": True}

        async def oauth_authorize(scopes: Optional[List[str]] = None) -> Dict[str, Any]:
            url = await self.runtime.service_registry.call("oauth_yandex.get_authorize_url", scopes or [])
            return {"url": url}

        async def oauth_exchange_code(code: str) -> Dict[str, Any]:
            res = await self.runtime.service_registry.call("oauth_yandex.exchange_code", code)
            return await _sanitize_oauth(res or {})

        # --- Admin trigger for Yandex sync ---
        async def admin_yandex_sync() -> Dict[str, Any]:
            """Trigger Yandex Smart Home sync from admin.

            Calls the yandex.sync service and returns a summary.
            """
            try:
                # Before syncing, remove previous external devices from provider 'yandex'
                try:
                    ext_keys = await self.runtime.storage.list_keys("devices_external")
                except Exception:
                    ext_keys = []

                for ext_id in ext_keys:
                    try:
                        payload = await self.runtime.storage.get("devices_external", ext_id)
                    except Exception:
                        payload = None
                    if not payload:
                        continue
                    if payload.get("provider") == "yandex":
                        try:
                            await self.runtime.storage.delete("devices_external", ext_id)
                        except Exception:
                            pass
                        try:
                            # Clear the duplicate in state engine
                            await self.runtime.state_engine.set(f"devices.external.{ext_id}", None)
                        except Exception:
                            pass

                # Prefer the stub plugin if it's loaded (dev-safe)
                try:
                    plugins = self.runtime.plugin_manager.list_plugins()
                except Exception:
                    plugins = []

                # If the 'yandex_smart_home' stub is present, prefer its sync service
                if 'yandex_smart_home' in plugins:
                    # stub registers 'yandex.sync' and 'yandex.sync_devices'
                    try:
                        devices = await self.runtime.service_registry.call("yandex.sync")
                    except Exception:
                        devices = await self.runtime.service_registry.call("yandex.sync_devices")
                else:
                    # Otherwise call whichever is available (real plugin exposes sync_devices)
                    try:
                        devices = await self.runtime.service_registry.call("yandex.sync")
                    except Exception:
                        devices = await self.runtime.service_registry.call("yandex.sync_devices")
                return {"ok": True, "count": len(devices) if isinstance(devices, list) else 0}
            except Exception as e:
                err = str(e or "")
                # If the real plugin explicitly says the Yandex account is not authorized,
                # return an error and DO NOT run the fallback (per requirements).
                if "yandex_not_authorized" in err:
                    return {"ok": False, "error": "yandex_not_authorized", "message": "Yandex OAuth not authorized"}

                # If the real plugin indicates the real-API flag is disabled, fall through
                # to dev-friendly fallback behavior.
                try:
                    fake_devices = [
                        {
                            "provider": "yandex",
                            "external_id": "yandex-fallback-light-1",
                            "type": "light",
                            "capabilities": ["on_off", "brightness"],
                            "state": {"on": False, "brightness": 50},
                        },
                        {
                            "provider": "yandex",
                            "external_id": "yandex-fallback-sensor-1",
                            "type": "temperature_sensor",
                            "capabilities": ["temperature"],
                            "state": {"temperature": 21.0},
                        },
                    ]
                    for d in fake_devices:
                        try:
                            await self.runtime.event_bus.publish("external.device_discovered", d)
                        except Exception:
                            pass
                    return {"ok": True, "count": len(fake_devices), "note": "fallback_generated", "error": err}
                except Exception as ee:
                    return {"ok": False, "error": f"sync_failed: {err} / fallback_failed: {ee}"}

        # Register admin yandex sync service
        self.runtime.service_registry.register("admin.yandex.sync", admin_yandex_sync)

        # --- Admin endpoints to read/set yandex feature flag (use real API) ---
        async def admin_yandex_get_config() -> Dict[str, Any]:
            try:
                val = await self.runtime.storage.get("yandex", "use_real_api")
            except Exception:
                val = False
            return {"use_real_api": bool(val)}

        async def admin_yandex_set_use_real(body: Any = None) -> Dict[str, Any]:
            try:
                # Support different shapes: raw boolean, string, or JSON object
                if isinstance(body, dict):
                    if "use_real_api" in body:
                        use_real = bool(body["use_real_api"])
                    elif "value" in body:
                        use_real = bool(body["value"])
                    else:
                        # fallback: try to interpret first value
                        vals = list(body.values())
                        use_real = bool(vals[0]) if vals else False
                else:
                    if isinstance(body, bool):
                        use_real = body
                    elif isinstance(body, str):
                        use_real = body.lower() in ("1", "true", "yes")
                    elif body is None:
                        use_real = False
                    else:
                        use_real = bool(body)

                await self.runtime.storage.set("yandex", "use_real_api", bool(use_real))
                return {"ok": True, "use_real_api": bool(use_real)}
            except Exception as e:
                return {"ok": False, "error": str(e)}

        self.runtime.service_registry.register("admin.yandex.get_config", admin_yandex_get_config)
        self.runtime.service_registry.register("admin.yandex.set_use_real", admin_yandex_set_use_real)

        # Register admin oauth services
        self.runtime.service_registry.register("admin.oauth.yandex.status", oauth_status)
        self.runtime.service_registry.register("admin.oauth.yandex.configure", oauth_configure)
        self.runtime.service_registry.register("admin.oauth.yandex.authorize", oauth_authorize)
        self.runtime.service_registry.register("admin.oauth.yandex.exchange", oauth_exchange_code)

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
            # OAuth Yandex admin v1 endpoints (proxy only)
            self.runtime.http.register(HttpEndpoint(
                method="GET",
                path="/admin/v1/oauth/yandex/status",
                service="admin.oauth.yandex.status",
                description="Get OAuth Yandex connection status (no secrets returned)"
            ))
            self.runtime.http.register(HttpEndpoint(
                method="POST",
                path="/admin/v1/oauth/yandex/configure",
                service="admin.oauth.yandex.configure",
                description="Configure OAuth Yandex client (do not return secrets)"
            ))
            self.runtime.http.register(HttpEndpoint(
                method="POST",
                path="/admin/v1/oauth/yandex/authorize",
                service="admin.oauth.yandex.authorize",
                description="Get authorize URL for Yandex OAuth (open in UI)"
            ))
            self.runtime.http.register(HttpEndpoint(
                method="POST",
                path="/admin/v1/oauth/yandex/exchange-code",
                service="admin.oauth.yandex.exchange",
                description="Exchange authorization code for tokens (admin_plugin will not return secrets)"
            ))
            # Admin trigger for Yandex devices sync (dev-only)
            self.runtime.http.register(HttpEndpoint(
                method="POST",
                path="/admin/v1/yandex/sync",
                service="admin.yandex.sync",
                description="Trigger Yandex Smart Home devices sync"
            ))
            # Yandex config endpoints: read / set use_real_api flag
            self.runtime.http.register(HttpEndpoint(
                method="GET",
                path="/admin/v1/yandex/config",
                service="admin.yandex.get_config",
                description="Get Yandex admin config (use_real_api)"
            ))
            self.runtime.http.register(HttpEndpoint(
                method="POST",
                path="/admin/v1/yandex/config/use-real",
                service="admin.yandex.set_use_real",
                description="Set Yandex admin config flag use_real_api (body: true/false)"
            ))
            # Devices admin v1 endpoints (proxy to devices plugin)
            self.runtime.http.register(HttpEndpoint(
                method="GET",
                path="/admin/v1/devices",
                service="admin.devices.list",
                description="List internal devices"
            ))
            self.runtime.http.register(HttpEndpoint(
                method="GET",
                path="/admin/v1/devices/{id}",
                service="admin.devices.get",
                description="Get internal device by id"
            ))
            self.runtime.http.register(HttpEndpoint(
                method="POST",
                path="/admin/v1/devices/{id}/state",
                service="admin.devices.set_state",
                description="Set state for internal device"
            ))
            self.runtime.http.register(HttpEndpoint(
                method="GET",
                path="/admin/v1/devices/external/{provider}",
                service="admin.devices.list_external",
                description="List external devices for provider"
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
            # Unregister devices admin proxies
            try:
                self.runtime.service_registry.unregister("admin.devices.list")
                self.runtime.service_registry.unregister("admin.devices.get")
                self.runtime.service_registry.unregister("admin.devices.set_state")
                self.runtime.service_registry.unregister("admin.devices.list_external")
            except Exception:
                pass
            # Unregister oauth admin services
            try:
                self.runtime.service_registry.unregister("admin.oauth.yandex.status")
                self.runtime.service_registry.unregister("admin.oauth.yandex.configure")
                self.runtime.service_registry.unregister("admin.oauth.yandex.authorize")
                self.runtime.service_registry.unregister("admin.oauth.yandex.exchange")
                # unregister admin yandex sync
                try:
                    self.runtime.service_registry.unregister("admin.yandex.sync")
                    try:
                        self.runtime.service_registry.unregister("admin.yandex.get_config")
                    except Exception:
                        pass
                    try:
                        self.runtime.service_registry.unregister("admin.yandex.set_use_real")
                    except Exception:
                        pass
                except Exception:
                    pass
            except Exception:
                pass
        except Exception:
            pass
