"""
AdminModule — встроенный модуль административных endpoints.

Предоставляет read-only административные сервисы и HTTP endpoints
для инспекции runtime состояния.
"""

from typing import Any, Dict, List, Optional
import time
import datetime
import asyncio

from core.runtime_module import RuntimeModule
from core.http_registry import HttpEndpoint


class AdminModule(RuntimeModule):
    """
    Модуль административных endpoints.
    
    Предоставляет read-only доступ к информации о runtime:
    - список плагинов, сервисов, HTTP endpoints
    - состояние state_engine и storage
    - proxy-сервисы для devices
    """

    @property
    def name(self) -> str:
        """Уникальное имя модуля."""
        return "admin"

    def __init__(self, runtime: Any):
        """Инициализация модуля."""
        super().__init__(runtime)
        self._admin_started_at: Optional[float] = None
        self._registered_services: List[str] = []

    async def register(self) -> None:
        """
        Регистрация модуля в CoreRuntime.
        
        Регистрирует все административные сервисы и HTTP endpoints.
        """
        # Record admin module start time
        try:
            self._admin_started_at = time.time()
        except Exception:
            self._admin_started_at = None

        # --- Basic admin services ---
        async def list_plugins() -> List[str]:
            return self.runtime.plugin_manager.list_plugins()

        async def list_services() -> List[str]:
            return await self.runtime.service_registry.list_services()

        async def list_http() -> List[Dict[str, Any]]:
            return [
                {"method": ep.method, "path": ep.path, "service": ep.service, "description": ep.description}
                for ep in self.runtime.http.list()
            ]

        async def state_keys() -> List[str]:
            return await self.runtime.state_engine.keys()

        async def state_get(key: str) -> Optional[Any]:
            return await self.runtime.state_engine.get(key)

        # --- Admin v1 read-only inventory services ---
        async def admin_v1_runtime() -> Dict[str, Any]:
            """Return runtime info: uptime (sec), started_at (ISO), version"""
            started_at_ts = self._admin_started_at
            if started_at_ts is None:
                started_at_iso = None
                uptime = None
            else:
                started_at_iso = datetime.datetime.fromtimestamp(started_at_ts).isoformat()
                uptime = int(time.time() - started_at_ts)

            version = getattr(self.runtime, "version", None) or "0.1.0"
            return {"uptime": uptime, "started_at": started_at_iso, "version": version}

        async def admin_v1_plugins() -> List[Dict[str, Any]]:
            res: List[Dict[str, Any]] = []
            services = await self.runtime.service_registry.list_services()
            http_eps = self.runtime.http.list()
            # Build mapping: plugin -> events subscribed
            events_map: Dict[str, List[str]] = {}
            try:
                handlers_map = getattr(self.runtime.event_bus, "_handlers", {})
                for ev, handlers in handlers_map.items():
                    for h in handlers:
                        owner = None
                        try:
                            # bound method? try to get plugin metadata
                            if hasattr(h, "__self__") and hasattr(h.__self__, "metadata"):
                                owner = h.__self__.metadata.name
                        except Exception:
                            owner = None
                        if not owner:
                            # fallback to qualname/module
                            try:
                                owner = getattr(h, "__qualname__", None)
                                if owner and "." in owner:
                                    owner = owner.split(".")[0]
                            except Exception:
                                owner = "unknown"
                        events_map.setdefault(owner or "unknown", []).append(ev)
            except Exception:
                events_map = {}

            for plugin_name in self.runtime.plugin_manager.list_plugins():
                state = self.runtime.plugin_manager.get_plugin_state(plugin_name)
                state_val = None
                try:
                    state_val = getattr(state, "value", str(state))
                except Exception:
                    state_val = str(state)
                started_flag = (state_val == "started")

                svc_count = 0
                try:
                    svc_count = len([s for s in services if s.split(".")[0] == plugin_name])
                except Exception:
                    svc_count = 0

                http_count = 0
                try:
                    http_count = len([ep for ep in http_eps if ep.service and ep.service.split(".")[0] == plugin_name])
                except Exception:
                    http_count = 0

                res.append({
                    "name": plugin_name,
                    "loaded": state_val in ("loaded", "started"),
                    "started": started_flag,
                    "services_count": svc_count,
                    "http_count": http_count,
                    "event_subscriptions": events_map.get(plugin_name, []),
                })
            return res

        async def admin_v1_services() -> List[Dict[str, str]]:
            svcs = []
            all_services = await self.runtime.service_registry.list_services()
            for s in all_services:
                owner = s.split(".")[0] if s and "." in s else ""
                svcs.append({"service_name": s, "plugin_name": owner})
            return svcs

        async def admin_v1_http() -> List[Dict[str, Any]]:
            out: List[Dict[str, Any]] = []
            for ep in self.runtime.http.list():
                owner = ep.service.split(".")[0] if ep.service and "." in ep.service else ""
                out.append({"method": ep.method, "path": ep.path, "service": ep.service, "plugin": owner})
            return out

        async def admin_v1_events() -> List[Dict[str, Any]]:
            out: List[Dict[str, Any]] = []
            try:
                handlers_map = getattr(self.runtime.event_bus, "_handlers", {})
                for ev, handlers in handlers_map.items():
                    subs = []
                    for h in handlers:
                        try:
                            plugin_name = None
                            if hasattr(h, "__self__") and hasattr(h.__self__, "metadata"):
                                plugin_name = h.__self__.metadata.name
                            else:
                                # fallback
                                plugin_name = getattr(h, "__qualname__", None)
                                if plugin_name and "." in plugin_name:
                                    plugin_name = plugin_name.split(".")[0]
                        except Exception:
                            plugin_name = "unknown"

                        handler_name = getattr(h, "__name__", None) or getattr(h, "__qualname__", repr(h))
                        subs.append({"plugin": plugin_name, "handler": handler_name})
                    out.append({"event_name": ev, "subscribers": subs})
            except Exception:
                pass
            return out

        async def admin_v1_storage() -> List[Dict[str, Any]]:
            # Return list of namespaces with key counts. Best-effort introspection of adapter.
            out: List[Dict[str, Any]] = []
            adapter = getattr(self.runtime.storage, "_adapter", None)
            if adapter is None:
                return out

            # SQLiteAdapter: query distinct namespaces
            try:
                if hasattr(adapter, "_get_connection"):
                    def _query_namespaces():
                        conn = adapter._get_connection()
                        cur = conn.execute("SELECT DISTINCT namespace FROM storage")
                        return [row[0] for row in cur.fetchall()]

                    namespaces = await asyncio.to_thread(_query_namespaces)
                    for ns in namespaces:
                        try:
                            keys = await self.runtime.storage.list_keys(ns)
                            out.append({"namespace": ns, "keys_count": len(keys)})
                        except Exception:
                            out.append({"namespace": ns, "keys_count": None})
                    return out
            except Exception:
                pass

            # Fallback: no way to list namespaces — return empty
            return out

        async def admin_v1_state() -> Dict[str, Any]:
            ks = []
            try:
                ks = await self.runtime.state_engine.keys()
            except Exception:
                ks = []
            out: Dict[str, Any] = {}
            for k in ks:
                try:
                    out[k] = await self.runtime.state_engine.get(k)
                except Exception:
                    out[k] = None
            return out

        # --- Devices proxy services (admin v1) ---
        async def admin_devices_list():
            return await self.runtime.service_registry.call("devices.list")

        async def admin_devices_get(id: Optional[str] = None, **kwargs):
            # HTTP layer may pass path param as 'id'
            device_id = id or kwargs.get("device_id") or kwargs.get("deviceId")
            if not device_id:
                raise ValueError("device id is required")
            return await self.runtime.service_registry.call("devices.get", device_id)

        async def admin_devices_set_state(id: Optional[str] = None, body: Any = None, **kwargs):
            # Accept path param 'id' and request body as 'body'
            device_id = id or kwargs.get("device_id") or kwargs.get("deviceId")

            # body содержит полный JSON из POST запроса
            # Expected format: {state: {on: boolean}} или {on: boolean}
            state = None
            if isinstance(body, dict):
                if "state" in body and isinstance(body["state"], dict):
                    state = body["state"]
                else:
                    # treat body itself as state
                    state = body
            
            if state is None or not isinstance(state, dict):
                state = {}

            # Normalize 'on' property to boolean
            if "on" in state:
                on_val = state["on"]
                if isinstance(on_val, str):
                    # Convert string "on"/"true" to boolean
                    state["on"] = on_val.lower() in ("on", "true", "1", "yes")
                else:
                    state["on"] = bool(on_val)
            
            # Support legacy 'power' property for backwards compatibility
            if "power" in state and "on" not in state:
                power_val = state.pop("power")
                if isinstance(power_val, str):
                    state["on"] = power_val.lower() in ("on", "true", "1", "yes")
                else:
                    state["on"] = bool(power_val)

            if not device_id:
                raise ValueError("device id is required")
            if "on" not in state:
                raise ValueError("state must contain 'on' property (boolean), e.g. {\"state\": {\"on\": true}}")

            # Proxy call to devices.set_state
            return await self.runtime.service_registry.call("devices.set_state", device_id, state)

        async def admin_devices_list_external(provider: Optional[str] = None, **kwargs):
            # provider может прийти из path params {provider}
            if provider is None:
                provider = kwargs.get("provider")
            return await self.runtime.service_registry.call("devices.list_external", provider)

        # --- Devices mapping admin proxies ---
        async def admin_devices_list_mappings() -> Any:
            try:
                return await self.runtime.service_registry.call("devices.list_mappings")
            except Exception as e:
                return {"ok": False, "error": str(e)}

        async def admin_devices_create_mapping(body: Any = None) -> Dict[str, Any]:
            # Accept either JSON body {external_id, internal_id} or raw args
            if isinstance(body, dict):
                ext = body.get("external_id") or body.get("externalId") or body.get("external")
                internal = body.get("internal_id") or body.get("internalId") or body.get("internal")
            elif isinstance(body, list) and len(body) >= 2:
                ext, internal = body[0], body[1]
            else:
                # Unsupported shape
                return {"ok": False, "error": "invalid_body"}
            try:
                return await self.runtime.service_registry.call("devices.create_mapping", ext, internal)
            except Exception as e:
                return {"ok": False, "error": str(e)}

        async def admin_devices_delete_mapping(external_id: str) -> Dict[str, Any]:
            try:
                return await self.runtime.service_registry.call("devices.delete_mapping", external_id)
            except Exception as e:
                return {"ok": False, "error": str(e)}

        async def admin_devices_auto_map(provider: Optional[str] = None) -> Dict[str, Any]:
            try:
                return await self.runtime.service_registry.call("devices.auto_map_external", provider)
            except Exception as e:
                return {"ok": False, "error": str(e)}


        # --- Integrations admin service ---
        async def admin_v1_integrations() -> List[Dict[str, Any]]:
            """Return list of registered integrations."""
            integrations = self.runtime.integrations.list()
            result = []
            for integration in integrations:
                # Get plugin state
                plugin_state = self.runtime.plugin_manager.get_plugin_state(integration.plugin_name)
                state_val = None
                try:
                    state_val = getattr(plugin_state, "value", str(plugin_state)) if plugin_state else None
                except Exception:
                    state_val = str(plugin_state) if plugin_state else None
                
                result.append({
                    "id": integration.id,
                    "name": integration.name,
                    "plugin_name": integration.plugin_name,
                    "description": integration.description,
                    "flags": [flag.value for flag in integration.flags],
                    "plugin_state": state_val,
                    "plugin_loaded": state_val in ("loaded", "started") if state_val else False,
                    "plugin_started": state_val == "started" if state_val else False,
                })
            return result

        # --- Auth management services ---
        from modules.api.auth import (
            create_api_key,
            create_user,
            create_session,
            validate_user_exists,
            verify_user_password,
            set_password,
            change_password,
            list_sessions,
            revoke_session,
            revoke_all_sessions,
            revoke_api_key,
            rotate_api_key,
            generate_access_token,
            create_refresh_token,
            get_or_create_jwt_secret,
            refresh_access_token,
            AUTH_API_KEYS_NAMESPACE,
            AUTH_USERS_NAMESPACE,
            AUTH_SESSIONS_NAMESPACE,
        )

        async def admin_auth_create_api_key(body: Any = None) -> Dict[str, Any]:
            """Create new API key."""
            if not isinstance(body, dict):
                return {"ok": False, "error": "invalid_body"}
            
            scopes = body.get("scopes", [])
            is_admin = body.get("is_admin", False)
            subject = body.get("subject")
            expires_at = body.get("expires_at")  # Опционально: timestamp для истечения
            
            try:
                api_key = await create_api_key(self.runtime, scopes, is_admin, subject, expires_at)
                return {"ok": True, "api_key": api_key}
            except Exception as e:
                return {"ok": False, "error": str(e)}

        async def admin_auth_list_api_keys() -> List[Dict[str, Any]]:
            """List all API keys (without actual keys, with metadata)."""
            try:
                keys = await self.runtime.storage.list_keys(AUTH_API_KEYS_NAMESPACE)
                result = []
                current_time = time.time()
                
                for key_id in keys:
                    try:
                        key_data = await self.runtime.storage.get(AUTH_API_KEYS_NAMESPACE, key_id)
                        if isinstance(key_data, dict):
                            expires_at = key_data.get("expires_at")
                            is_expired = expires_at is not None and current_time > expires_at
                            
                            # Пропускаем истекшие ключи
                            if is_expired:
                                continue
                            
                            key_info = {
                                "id": key_id[:16] + "...",  # Обрезаем для безопасности
                                "subject": key_data.get("subject"),
                                "scopes": key_data.get("scopes", []),
                                "is_admin": key_data.get("is_admin", False),
                                "created_at": key_data.get("created_at"),
                                "last_used": key_data.get("last_used"),
                                "expires_at": expires_at,
                                "is_expired": is_expired,
                            }
                            result.append(key_info)
                    except Exception:
                        pass
                
                # Сортируем по created_at (новые сначала)
                result.sort(key=lambda x: x.get("created_at", 0), reverse=True)
                return result
            except Exception:
                return []

        async def admin_auth_create_user(body: Any = None) -> Dict[str, Any]:
            """Create new user."""
            if not isinstance(body, dict):
                return {"ok": False, "error": "invalid_body"}
            
            user_id = body.get("user_id")
            if not user_id:
                return {"ok": False, "error": "user_id required"}
            
            scopes = body.get("scopes", [])
            is_admin = body.get("is_admin", False)
            username = body.get("username")
            password = body.get("password")  # Опционально
            
            try:
                await create_user(self.runtime, user_id, scopes, is_admin, username, password)
                return {"ok": True, "user_id": user_id}
            except Exception as e:
                return {"ok": False, "error": str(e)}

        async def admin_auth_list_users() -> List[Dict[str, Any]]:
            """List all users."""
            try:
                user_ids = await self.runtime.storage.list_keys(AUTH_USERS_NAMESPACE)
                result = []
                for user_id in user_ids:
                    try:
                        user_data = await self.runtime.storage.get(AUTH_USERS_NAMESPACE, user_id)
                        if isinstance(user_data, dict):
                            result.append({
                                "user_id": user_id,
                                "username": user_data.get("username"),
                                "scopes": user_data.get("scopes", []),
                                "is_admin": user_data.get("is_admin", False),
                                "created_at": user_data.get("created_at"),
                            })
                    except Exception:
                        pass
                return result
            except Exception:
                return []

        async def admin_auth_login(body: Any = None) -> Dict[str, Any]:
            """Login with password authentication, returns JWT access token and refresh token."""
            if not isinstance(body, dict):
                return {"ok": False, "error": "invalid_body"}
            
            user_id = body.get("user_id")
            password = body.get("password")
            
            if not user_id:
                return {"ok": False, "error": "user_id required"}
            
            if not password:
                return {"ok": False, "error": "password required"}
            
            if not await validate_user_exists(self.runtime, user_id):
                return {"ok": False, "error": "user not found"}
            
            # Проверяем пароль
            if not await verify_user_password(self.runtime, user_id, password):
                return {"ok": False, "error": "invalid_password"}
            
            try:
                # Получаем данные пользователя
                user_data = await self.runtime.storage.get(AUTH_USERS_NAMESPACE, user_id)
                if not isinstance(user_data, dict):
                    return {"ok": False, "error": "user data not found"}
                
                scopes = user_data.get("scopes", [])
                is_admin = user_data.get("is_admin", False)
                
                # Получаем опциональные метаданные из body
                client_ip = body.get("client_ip")
                user_agent = body.get("user_agent")
                
                # Генерируем JWT access token
                secret = await get_or_create_jwt_secret(self.runtime)
                access_token = generate_access_token(user_id, scopes, is_admin, secret)
                
                # Создаём refresh token
                refresh_token = await create_refresh_token(
                    self.runtime,
                    user_id,
                    client_ip=client_ip,
                    user_agent=user_agent
                )
                
                return {
                    "ok": True,
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "expires_in": 900,  # 15 минут в секундах
                    "token_type": "Bearer"
                }
            except Exception as e:
                return {"ok": False, "error": str(e)}
        
        async def admin_auth_refresh(body: Any = None) -> Dict[str, Any]:
            """Refresh access token using refresh token."""
            if not isinstance(body, dict):
                return {"ok": False, "error": "invalid_body"}
            
            refresh_token = body.get("refresh_token")
            if not refresh_token:
                return {"ok": False, "error": "refresh_token required"}
            
            try:
                access_token, new_refresh_token = await refresh_access_token(
                    self.runtime,
                    refresh_token,
                    rotate_refresh=True
                )
                
                result = {
                    "ok": True,
                    "access_token": access_token,
                    "expires_in": 900,
                    "token_type": "Bearer"
                }
                
                # Добавляем новый refresh token, если он был создан
                if new_refresh_token:
                    result["refresh_token"] = new_refresh_token
                
                return result
            except ValueError as e:
                return {"ok": False, "error": str(e)}
            except Exception as e:
                return {"ok": False, "error": str(e)}
        
        async def admin_auth_set_password(body: Any = None) -> Dict[str, Any]:
            """Set password for user."""
            if not isinstance(body, dict):
                return {"ok": False, "error": "invalid_body"}
            
            user_id = body.get("user_id")
            password = body.get("password")
            
            if not user_id:
                return {"ok": False, "error": "user_id required"}
            
            if not password:
                return {"ok": False, "error": "password required"}
            
            try:
                await set_password(self.runtime, user_id, password)
                return {"ok": True, "user_id": user_id}
            except Exception as e:
                return {"ok": False, "error": str(e)}
        
        async def admin_auth_change_password(body: Any = None) -> Dict[str, Any]:
            """Change password for user (requires old password)."""
            if not isinstance(body, dict):
                return {"ok": False, "error": "invalid_body"}
            
            user_id = body.get("user_id")
            old_password = body.get("old_password")
            new_password = body.get("new_password")
            
            if not user_id:
                return {"ok": False, "error": "user_id required"}
            
            if not old_password:
                return {"ok": False, "error": "old_password required"}
            
            if not new_password:
                return {"ok": False, "error": "new_password required"}
            
            try:
                await change_password(self.runtime, user_id, old_password, new_password)
                return {"ok": True, "user_id": user_id}
            except Exception as e:
                return {"ok": False, "error": str(e)}
        
        async def admin_auth_list_sessions(user_id: Optional[str] = None) -> List[Dict[str, Any]]:
            """
            List active sessions (optionally filtered by user_id).
            
            Args:
                user_id: опциональный query параметр для фильтрации по пользователю
            """
            try:
                return await list_sessions(self.runtime, user_id)
            except Exception:
                return []
        
        async def admin_auth_revoke_session(body: Any = None) -> Dict[str, Any]:
            """Revoke a specific session."""
            if not isinstance(body, dict):
                return {"ok": False, "error": "invalid_body"}
            
            session_id = body.get("session_id")
            if not session_id:
                return {"ok": False, "error": "session_id required"}
            
            try:
                await revoke_session(self.runtime, session_id)
                return {"ok": True, "session_id": session_id[:16] + "..."}
            except Exception as e:
                return {"ok": False, "error": str(e)}
        
        async def admin_auth_revoke_all_sessions(body: Any = None) -> Dict[str, Any]:
            """Revoke all sessions for a user."""
            if not isinstance(body, dict):
                return {"ok": False, "error": "invalid_body"}
            
            user_id = body.get("user_id")
            if not user_id:
                return {"ok": False, "error": "user_id required"}
            
            try:
                revoked_count = await revoke_all_sessions(self.runtime, user_id)
                return {"ok": True, "user_id": user_id, "revoked_count": revoked_count}
            except Exception as e:
                return {"ok": False, "error": str(e)}
        
        async def admin_auth_revoke_api_key(body: Any = None) -> Dict[str, Any]:
            """Revoke an API key."""
            if not isinstance(body, dict):
                return {"ok": False, "error": "invalid_body"}
            
            api_key = body.get("api_key")
            if not api_key:
                return {"ok": False, "error": "api_key required"}
            
            try:
                await revoke_api_key(self.runtime, api_key)
                return {"ok": True, "api_key": api_key[:16] + "..."}
            except Exception as e:
                return {"ok": False, "error": str(e)}
        
        async def admin_auth_rotate_api_key(body: Any = None) -> Dict[str, Any]:
            """Rotate an API key (create new, revoke old)."""
            if not isinstance(body, dict):
                return {"ok": False, "error": "invalid_body"}
            
            old_api_key = body.get("old_api_key")
            expires_at = body.get("expires_at")  # Опционально
            
            if not old_api_key:
                return {"ok": False, "error": "old_api_key required"}
            
            try:
                new_api_key = await rotate_api_key(self.runtime, old_api_key, expires_at)
                return {"ok": True, "new_api_key": new_api_key, "old_api_key": old_api_key[:16] + "..."}
            except Exception as e:
                return {"ok": False, "error": str(e)}

        # Register all services
        service_registrations = [
            ("admin.list_plugins", list_plugins),
            ("admin.list_services", list_services),
            ("admin.list_http", list_http),
            ("admin.state_keys", state_keys),
            ("admin.state_get", state_get),
            ("admin.v1.runtime", admin_v1_runtime),
            ("admin.v1.plugins", admin_v1_plugins),
            ("admin.v1.services", admin_v1_services),
            ("admin.v1.http", admin_v1_http),
            ("admin.v1.events", admin_v1_events),
            ("admin.v1.storage", admin_v1_storage),
            ("admin.v1.state", admin_v1_state),
            ("admin.devices.list", admin_devices_list),
            ("admin.devices.get", admin_devices_get),
            ("admin.devices.set_state", admin_devices_set_state),
            ("admin.devices.list_external", admin_devices_list_external),
            ("admin.devices.list_mappings", admin_devices_list_mappings),
            ("admin.devices.create_mapping", admin_devices_create_mapping),
            ("admin.devices.delete_mapping", admin_devices_delete_mapping),
            ("admin.devices.auto_map", admin_devices_auto_map),
            ("admin.v1.integrations", admin_v1_integrations),
            ("admin.auth.create_api_key", admin_auth_create_api_key),
            ("admin.auth.list_api_keys", admin_auth_list_api_keys),
            ("admin.auth.create_user", admin_auth_create_user),
            ("admin.auth.list_users", admin_auth_list_users),
            ("admin.auth.login", admin_auth_login),
            ("admin.auth.refresh", admin_auth_refresh),
            ("admin.auth.set_password", admin_auth_set_password),
            ("admin.auth.change_password", admin_auth_change_password),
            ("admin.auth.list_sessions", admin_auth_list_sessions),
            ("admin.auth.revoke_session", admin_auth_revoke_session),
            ("admin.auth.revoke_all_sessions", admin_auth_revoke_all_sessions),
            ("admin.auth.revoke_api_key", admin_auth_revoke_api_key),
            ("admin.auth.rotate_api_key", admin_auth_rotate_api_key),
        ]

        for name, func in service_registrations:
            try:
                await self.runtime.service_registry.register(name, func)
                self._registered_services.append(name)
            except ValueError:
                # Already registered - skip
                continue

        # Register HTTP endpoints
        http_endpoints = [
            HttpEndpoint(method="GET", path="/admin/plugins", service="admin.list_plugins", description="List loaded plugins"),
            HttpEndpoint(method="GET", path="/admin/services", service="admin.list_services", description="List registered services"),
            HttpEndpoint(method="GET", path="/admin/http", service="admin.list_http", description="List HTTP endpoints"),
            HttpEndpoint(method="GET", path="/admin/state/keys", service="admin.state_keys", description="List state keys"),
            HttpEndpoint(method="GET", path="/admin/state/{key}", service="admin.state_get", description="Get state value by key"),
            HttpEndpoint(method="GET", path="/admin/v1/runtime", service="admin.v1.runtime", description="Runtime info: uptime, started_at, version"),
            HttpEndpoint(method="GET", path="/admin/v1/plugins", service="admin.v1.plugins", description="List plugins with stats"),
            HttpEndpoint(method="GET", path="/admin/v1/services", service="admin.v1.services", description="List services and owning plugin"),
            HttpEndpoint(method="GET", path="/admin/v1/http", service="admin.v1.http", description="List HTTP contracts"),
            HttpEndpoint(method="GET", path="/admin/v1/events", service="admin.v1.events", description="List events and subscribers"),
            HttpEndpoint(method="GET", path="/admin/v1/storage", service="admin.v1.storage", description="List storage namespaces and key counts"),
            HttpEndpoint(method="GET", path="/admin/v1/state", service="admin.v1.state", description="Read-only state engine dump"),
            HttpEndpoint(method="GET", path="/admin/v1/devices", service="admin.devices.list", description="List internal devices"),
            HttpEndpoint(method="GET", path="/admin/v1/devices/mappings", service="admin.devices.list_mappings", description="List external->internal device mappings"),
            HttpEndpoint(method="POST", path="/admin/v1/devices/mappings", service="admin.devices.create_mapping", description="Create mapping: body {external_id, internal_id}"),
            HttpEndpoint(method="DELETE", path="/admin/v1/devices/mappings/{external_id}", service="admin.devices.delete_mapping", description="Delete mapping by external_id"),
            HttpEndpoint(method="POST", path="/admin/v1/devices/mappings/auto-map/{provider}", service="admin.devices.auto_map", description="Auto-map external devices for provider to internal devices"),
            HttpEndpoint(method="GET", path="/admin/v1/devices/{id}", service="admin.devices.get", description="Get internal device by id"),
            HttpEndpoint(method="POST", path="/admin/v1/devices/{id}/state", service="admin.devices.set_state", description="Set state for internal device"),
            HttpEndpoint(method="GET", path="/admin/v1/devices/external/{provider}", service="admin.devices.list_external", description="List external devices for provider"),
            HttpEndpoint(method="GET", path="/admin/v1/integrations", service="admin.v1.integrations", description="List registered integrations"),
            HttpEndpoint(method="POST", path="/admin/v1/auth/api-keys", service="admin.auth.create_api_key", description="Create new API key (body: {scopes, is_admin?, subject?, expires_at?})"),
            HttpEndpoint(method="GET", path="/admin/v1/auth/api-keys", service="admin.auth.list_api_keys", description="List all API keys (without actual keys, with metadata)"),
            HttpEndpoint(method="POST", path="/admin/v1/auth/api-keys/revoke", service="admin.auth.revoke_api_key", description="Revoke an API key (body: {api_key})"),
            HttpEndpoint(method="POST", path="/admin/v1/auth/api-keys/rotate", service="admin.auth.rotate_api_key", description="Rotate an API key (body: {old_api_key, expires_at?})"),
            HttpEndpoint(method="POST", path="/admin/v1/auth/users", service="admin.auth.create_user", description="Create new user (body: {user_id, scopes, is_admin?, username?, password?})"),
            HttpEndpoint(method="GET", path="/admin/v1/auth/users", service="admin.auth.list_users", description="List all users"),
            HttpEndpoint(method="POST", path="/admin/v1/auth/login", service="admin.auth.login", description="Login with password, returns JWT access_token and refresh_token (body: {user_id, password, client_ip?, user_agent?})"),
            HttpEndpoint(method="POST", path="/admin/v1/auth/refresh", service="admin.auth.refresh", description="Refresh access token using refresh_token (body: {refresh_token})"),
            HttpEndpoint(method="POST", path="/admin/v1/auth/password/set", service="admin.auth.set_password", description="Set password for user (body: {user_id, password})"),
            HttpEndpoint(method="POST", path="/admin/v1/auth/password/change", service="admin.auth.change_password", description="Change password for user (body: {user_id, old_password, new_password})"),
            HttpEndpoint(method="GET", path="/admin/v1/auth/sessions", service="admin.auth.list_sessions", description="List active sessions (query: user_id?)"),
            HttpEndpoint(method="POST", path="/admin/v1/auth/sessions/revoke", service="admin.auth.revoke_session", description="Revoke a specific session (body: {session_id})"),
            HttpEndpoint(method="POST", path="/admin/v1/auth/sessions/revoke-all", service="admin.auth.revoke_all_sessions", description="Revoke all sessions for a user (body: {user_id})"),
        ]

        for ep in http_endpoints:
            try:
                self.runtime.http.register(ep)
            except Exception:
                # Best-effort: не блокируем загрузку
                pass

    async def start(self) -> None:
        """
        Запуск модуля.
        
        В текущей реализации admin не требует инициализации при старте.
        """
        pass

    async def stop(self) -> None:
        """
        Остановка модуля.
        
        Отменяет регистрацию всех сервисов.
        """
        for service_name in self._registered_services:
            try:
                await self.runtime.service_registry.unregister(service_name)
            except Exception:
                pass
        self._registered_services.clear()
