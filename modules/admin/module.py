"""
AdminModule — встроенный модуль административных endpoints.

Предоставляет read-only административные сервисы и HTTP endpoints
для инспекции runtime состояния.

После C3: AdminModule только регистрирует endpoints и сервисы.
Логика вынесена в modules/admin/services/.
"""

from typing import Any, Dict, List, Optional
import time

from core.runtime_module import RuntimeModule
from core.http_registry import HttpEndpoint
from modules.admin.services import (
    get_runtime_info,
    list_plugins,
    list_services,
    list_http_endpoints,
    list_events,
    get_dashboard,
    list_storage_namespaces,
    get_state,
    list_state_keys,
    get_state_value,
)


class AdminModule(RuntimeModule):
    """
    Модуль административных endpoints.
    
    Предоставляет read-only доступ к информации о runtime:
    - список плагинов, сервисов, HTTP endpoints
    - состояние state_engine и storage
    - proxy-сервисы для devices
    
    После C3: тонкий слой регистрации, логика в services/.
    """

    @property
    def name(self) -> str:
        """Уникальное имя модуля."""
        return "admin"

    def __init__(self, runtime: Any):
        """Инициализация модуля."""
        super().__init__(runtime)
        self._admin_started_at: Optional[float] = None

    async def register(self) -> None:
        """
        Регистрация модуля в CoreRuntime.
        
        Регистрирует все административные сервисы и HTTP endpoints.
        """
        # Record admin module start time
        self._admin_started_at = time.time()
        
        # Register introspection HTTP endpoints
        introspection_endpoints = [
            ("/admin/v1/runtime", "admin.v1.runtime", "Get runtime info"),
            ("/admin/v1/plugins", "admin.v1.plugins", "List all plugins"),
            ("/admin/v1/services", "admin.v1.services", "List all services"),
            ("/admin/v1/http", "admin.v1.http", "List all HTTP endpoints"),
            ("/admin/v1/events", "admin.v1.events", "List event subscriptions"),
            ("/admin/v1/dashboard", "admin.v1.dashboard", "Get dashboard (aggregated data)"),
            ("/admin/v1/storage", "admin.v1.storage", "List storage namespaces"),
            ("/admin/v1/state", "admin.v1.state", "Get all state"),
            ("/admin/v1/state/keys", "admin.v1.state.keys", "List state keys"),
        ]
        
        for path, service, description in introspection_endpoints:
            self.runtime.http.register(HttpEndpoint(
                method="GET",
                path=path,
                service=service,
                description=description
            ))
        
        # Register GET with path param
        self.runtime.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/state/{key}",
            service="admin.v1.state.get",
            description="Get state value by key"
        ))
        
        # Register operations handlers
        try:
            from modules.operations.handlers import (
                handle_device_set_state,
                handle_yandex_sync,
                handle_yandex_check_online,
                handle_oauth_refresh,
                handle_mappings_create,
                handle_mappings_delete,
                handle_mappings_auto,
            )
            
            ops_mgr = self.runtime.operations
            if ops_mgr:
                ops_mgr.register_handler("device.set_state", handle_device_set_state)
                ops_mgr.register_handler("yandex.sync", handle_yandex_sync)
                ops_mgr.register_handler("yandex.check_devices_online", handle_yandex_check_online)
                ops_mgr.register_handler("oauth.refresh_token", handle_oauth_refresh)
                ops_mgr.register_handler("mappings.create", handle_mappings_create)
                ops_mgr.register_handler("mappings.delete", handle_mappings_delete)
                ops_mgr.register_handler("mappings.auto", handle_mappings_auto)
        except Exception as e:
            import traceback
            traceback.print_exc()

        # --- Register webhook demo service (C4) ---
        async def webhook_test_service(payload, **kwargs):
            """Demo webhook service that logs incoming webhook payload."""
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

        # --- Register introspection services (using extracted logic) ---
        
        await self.runtime.service_registry.register(
            "admin.v1.runtime",
            lambda: get_runtime_info(self.runtime, self._admin_started_at)
        )
        
        await self.runtime.service_registry.register(
            "admin.v1.plugins",
            lambda: list_plugins(self.runtime)
        )
        
        await self.runtime.service_registry.register(
            "admin.v1.services",
            lambda: list_services(self.runtime)
        )
        
        await self.runtime.service_registry.register(
            "admin.v1.http",
            lambda: list_http_endpoints(self.runtime)
        )
        
        await self.runtime.service_registry.register(
            "admin.v1.events",
            lambda: list_events(self.runtime)
        )
        
        await self.runtime.service_registry.register(
            "admin.v1.dashboard",
            lambda: get_dashboard(self.runtime, self._admin_started_at)
        )
        
        await self.runtime.service_registry.register(
            "admin.v1.storage",
            lambda: list_storage_namespaces(self.runtime)
        )
        
        await self.runtime.service_registry.register(
            "admin.v1.state",
            lambda: get_state(self.runtime)
        )
        
        await self.runtime.service_registry.register(
            "admin.v1.state.keys",
            lambda: list_state_keys(self.runtime)
        )
        
        await self.runtime.service_registry.register(
            "admin.v1.state.get",
            lambda key: get_state_value(self.runtime, key)
        )
        
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

            # Route through operations subsystem
            operations_mgr = getattr(self.runtime, "operations", None)
            if not operations_mgr:
                # Fallback to direct call if operations not available
                return await self.runtime.service_registry.call("devices.set_state", device_id, state)
            
            from core.operations import OperationInitiator, OperationInitiatorKind
            
            initiator = OperationInitiator(
                kind=OperationInitiatorKind.ADMIN,
                user_id=None,
            )
            
            operation = await operations_mgr.create(
                op_type="device.set_state",
                params={"device_id": device_id, "state": state},
                initiator=initiator,
            )
            
            result = await operations_mgr.execute(operation)
            
            return {
                "operation_id": result.operation_id,
                "status": result.status.value,
                "result": result.result,
                "error": result.error.to_dict() if result.error else None,
            }

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
            user_id = body.get("user_id")  # Опционально: для Resource-Based Authorization с ACL
            
            try:
                api_key = await create_api_key(self.runtime, scopes, is_admin, subject, expires_at, user_id)
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

        async def admin_auth_initialize(body: Any = None) -> Dict[str, Any]:
            """Initialize system by creating first admin user (public endpoint, no auth required)."""
            if not isinstance(body, dict):
                return {"ok": False, "error": "invalid_body"}
            
            user_id = body.get("user_id", "admin")
            username = body.get("username", "Administrator")
            password = body.get("password")
            
            if not password:
                return {"ok": False, "error": "password required"}
            
            try:
                # Проверяем, есть ли уже админ
                user_ids = await self.runtime.storage.list_keys(AUTH_USERS_NAMESPACE)
                has_admin = False
                for uid in user_ids:
                    try:
                        user_data = await self.runtime.storage.get(AUTH_USERS_NAMESPACE, uid)
                        if isinstance(user_data, dict) and user_data.get("is_admin", False):
                            has_admin = True
                            break
                    except Exception:
                        pass
                
                if has_admin:
                    return {"ok": False, "error": "System already initialized. Admin user exists."}
                
                # Создаём первого админа
                await create_user(
                    self.runtime,
                    user_id,
                    ["admin.*"],  # Полные права админа
                    is_admin=True,
                    username=username,
                    password=password
                )
                
                return {"ok": True, "user_id": user_id, "message": "System initialized successfully"}
            except ValueError as e:
                return {"ok": False, "error": str(e)}
            except Exception as e:
                return {"ok": False, "error": f"Initialization failed: {str(e)}"}

        async def admin_auth_login(body: Any = None, request: Any = None, response: Any = None) -> Dict[str, Any]:
            """Login with password authentication, sets HttpOnly cookies with tokens."""
            if not isinstance(body, dict):
                return {"ok": False, "error": "invalid_body"}
            
            user_id = body.get("user_id")
            password = body.get("password")
            
            if not user_id:
                return {"ok": False, "error": "user_id required"}
            
            if not password:
                return {"ok": False, "error": "password required"}
            
            # SECURITY: защита от account enumeration
            # Никогда не раскрываем, существует ли пользователь — всегда возвращаем одинаковую ошибку.
            if not await validate_user_exists(self.runtime, user_id):
                return {"ok": False, "error": "invalid_credentials"}
            
            # Проверяем пароль
            if not await verify_user_password(self.runtime, user_id, password):
                return {"ok": False, "error": "invalid_credentials"}
            
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
                
                # Set HttpOnly cookies if response object is available
                if response is not None:
                    import secrets
                    cfg = getattr(self.runtime, "_config", None)
                    cookies_samesite = getattr(cfg, "cookies_samesite", "lax") if cfg is not None else "lax"
                    cookies_domain = getattr(cfg, "cookies_domain", "localhost") if cfg is not None else "localhost"
                    # secure: None => auto (https => True), иначе берём из config
                    secure_cfg = getattr(cfg, "cookies_secure", None) if cfg is not None else None
                    req_scheme = getattr(getattr(request, "url", None), "scheme", "http") if request is not None else "http"
                    secure_cookie = (req_scheme == "https") if secure_cfg is None else bool(secure_cfg)
                    csrf_cookie_name = getattr(cfg, "csrf_cookie_name", "csrf_token") if cfg is not None else "csrf_token"

                    csrf_token = secrets.token_urlsafe(32)

                    # HttpOnly cookies for secure token storage
                    response.set_cookie(
                        key="access_token",
                        value=access_token,
                        max_age=900,  # 15 минут
                        httponly=True,
                        secure=secure_cookie,
                        samesite=cookies_samesite,
                        domain=cookies_domain,
                        path="/"
                    )
                    response.set_cookie(
                        key="refresh_token",
                        value=refresh_token,
                        max_age=2592000,  # 30 дней
                        httponly=True,
                        secure=secure_cookie,
                        samesite=cookies_samesite,
                        domain=cookies_domain,
                        path="/"
                    )
                    # CSRF double-submit token (не HttpOnly, чтобы фронт мог читать и слать в header)
                    response.set_cookie(
                        key=csrf_cookie_name,
                        value=csrf_token,
                        max_age=2592000,
                        httponly=False,
                        secure=secure_cookie,
                        samesite=cookies_samesite,
                        domain=cookies_domain,
                        path="/"
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
        
        async def admin_auth_refresh(body: Any = None, request: Any = None, response: Any = None) -> Dict[str, Any]:
            """Refresh access token using refresh token from cookie or body."""
            # Try to get refresh_token from cookie first, then from body
            refresh_token = None
            if request is not None:
                refresh_token = request.cookies.get("refresh_token")
            
            if not refresh_token and isinstance(body, dict):
                refresh_token = body.get("refresh_token")
            
            if not refresh_token:
                return {"ok": False, "error": "refresh_token required"}
            
            try:
                access_token, new_refresh_token = await refresh_access_token(
                    self.runtime,
                    refresh_token,
                    rotate_refresh=True
                )
                
                # Set HttpOnly cookies if response object is available
                if response is not None:
                    import secrets
                    cfg = getattr(self.runtime, "_config", None)
                    cookies_samesite = getattr(cfg, "cookies_samesite", "lax") if cfg is not None else "lax"
                    cookies_domain = getattr(cfg, "cookies_domain", "localhost") if cfg is not None else "localhost"
                    secure_cfg = getattr(cfg, "cookies_secure", None) if cfg is not None else None
                    req_scheme = getattr(getattr(request, "url", None), "scheme", "http") if request is not None else "http"
                    secure_cookie = (req_scheme == "https") if secure_cfg is None else bool(secure_cfg)
                    csrf_cookie_name = getattr(cfg, "csrf_cookie_name", "csrf_token") if cfg is not None else "csrf_token"

                    csrf_token = secrets.token_urlsafe(32)

                    response.set_cookie(
                        key="access_token",
                        value=access_token,
                        max_age=900,  # 15 минут
                        httponly=True,
                        secure=secure_cookie,
                        samesite=cookies_samesite,
                        domain=cookies_domain,
                        path="/"
                    )
                    if new_refresh_token:
                        response.set_cookie(
                            key="refresh_token",
                            value=new_refresh_token,
                            max_age=2592000,  # 30 дней
                            httponly=True,
                            secure=secure_cookie,
                            samesite=cookies_samesite,
                            domain=cookies_domain,
                            path="/"
                        )
                    # обновляем CSRF токен
                    response.set_cookie(
                        key=csrf_cookie_name,
                        value=csrf_token,
                        max_age=2592000,
                        httponly=False,
                        secure=secure_cookie,
                        samesite=cookies_samesite,
                        domain=cookies_domain,
                        path="/"
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
        
        async def admin_auth_me(request: Any = None) -> Dict[str, Any]:
            """Get current user information from request context."""
            # Получаем context из request.state (устанавливается middleware)
            if request is None:
                return {"ok": False, "error": "request not available"}
            
            # Сначала проверяем, есть ли вообще админы в системе
            try:
                user_ids = await self.runtime.storage.list_keys(AUTH_USERS_NAMESPACE)
                has_admin = False
                for user_id in user_ids:
                    try:
                        user_data = await self.runtime.storage.get(AUTH_USERS_NAMESPACE, user_id)
                        if isinstance(user_data, dict) and user_data.get("is_admin", False):
                            has_admin = True
                            break
                    except Exception:
                        pass
                
                # Если админа нет - возвращаем специальный статус
                if not has_admin:
                    return {"ok": False, "needs_initialization": True, "error": "System not initialized"}
            except Exception:
                # В случае ошибки проверки продолжаем обычную логику
                pass
            
            from modules.api.auth.middleware import get_request_context
            context = await get_request_context(request)
            
            # NOTE: Проверка context здесь допустима — это boundary layer (AdminModule),
            # где проверка авторизации выполняется на HTTP уровне.
            if context is None or context.user_id is None:
                return {"ok": False, "error": "not authenticated"}
            
            try:
                # Получаем данные пользователя из storage
                user_data = await self.runtime.storage.get(AUTH_USERS_NAMESPACE, context.user_id)
                if not isinstance(user_data, dict):
                    return {"ok": False, "error": "user data not found"}
                
                return {
                    "ok": True,
                    "user_id": context.user_id,
                    "username": user_data.get("username"),
                    "scopes": list(context.scopes) if context.scopes else user_data.get("scopes", []),
                    "is_admin": context.is_admin or user_data.get("is_admin", False),
                    "created_at": user_data.get("created_at"),
                    "source": context.source,
                }
            except Exception as e:
                return {"ok": False, "error": str(e)}

        # Wrapper for yandex.sync_devices to handle errors properly
        async def admin_v1_yandex_sync() -> Dict[str, Any]:
            """Wrapper for yandex.sync_devices that routes through operations subsystem."""
            try:
                # Route through operations subsystem
                operations_mgr = getattr(self.runtime, "operations", None)
                if not operations_mgr:
                    # Fallback to direct call if operations not available
                    if not await self.runtime.service_registry.has_service("yandex.sync_devices"):
                        return {"ok": False, "error": "yandex.sync_devices service not available"}
                    
                    try:
                        use_real = await self.runtime.storage.get("yandex", "use_real_api")
                        if not use_real:
                            await self.runtime.storage.set("yandex", "use_real_api", {"enabled": True})
                    except Exception:
                        await self.runtime.storage.set("yandex", "use_real_api", {"enabled": True})
                    
                    devices = await self.runtime.service_registry.call("yandex.sync_devices")
                    
                    try:
                        if await self.runtime.service_registry.has_service("devices.auto_map_external"):
                            await self.runtime.service_registry.call("devices.auto_map_external", "yandex")
                    except Exception:
                        pass
                    
                    return {
                        "ok": True,
                        "devices": devices if isinstance(devices, list) else [],
                        "count": len(devices) if isinstance(devices, list) else 0,
                    }
                
                # Create operation
                from core.operations import OperationInitiator, OperationInitiatorKind
                
                initiator = OperationInitiator(
                    kind=OperationInitiatorKind.ADMIN,
                    user_id=None,
                )
                
                operation = await operations_mgr.create(
                    op_type="yandex.sync",
                    params={},
                    initiator=initiator,
                )
                
                result = await operations_mgr.execute(operation)
                
                return {
                    "ok": result.status.value == "success",
                    "operation_id": result.operation_id,
                    "status": result.status.value,
                    "result": result.result,
                    "error": result.error.to_dict() if result.error else None,
                }
            except RuntimeError as e:
                error_msg = str(e)
                if "yandex_not_authorized" in error_msg:
                    return {"ok": False, "error": "Yandex OAuth not authorized. Please configure and authorize OAuth first."}
                elif "use_real_api_disabled" in error_msg:
                    return {"ok": False, "error": "Real API is disabled. Enable it in storage: yandex.use_real_api = true"}
                else:
                    return {"ok": False, "error": error_msg}
            except Exception as e:
                return {"ok": False, "error": f"Sync failed: {str(e)}"}

        async def admin_v1_yandex_check_online() -> Dict[str, Any]:
            """Wrapper for yandex.check_devices_online that handles errors and returns proper format."""
            try:
                # Check if service exists
                if not await self.runtime.service_registry.has_service("yandex.check_devices_online"):
                    return {"ok": False, "error": "yandex.check_devices_online service not available"}
                
                # Call the service
                result = await self.runtime.service_registry.call("yandex.check_devices_online")
                
                if isinstance(result, dict):
                    return {
                        "ok": True,
                        **result
                    }
                else:
                    return {
                        "ok": True,
                        "checked": 0,
                        "online": 0,
                        "offline": 0,
                        "errors": []
                    }
            except RuntimeError as e:
                error_msg = str(e)
                # Handle specific error cases
                if "yandex_not_authorized" in error_msg:
                    return {"ok": False, "error": "Yandex OAuth not authorized. Please configure and authorize OAuth first."}
                else:
                    return {"ok": False, "error": error_msg}
            except Exception as e:
                return {"ok": False, "error": f"Check online failed: {str(e)}"}

        # ======================================================================
        # Operations endpoints
        # ======================================================================
        
        async def admin_operations_create(body: Any = None, **kwargs) -> Dict[str, Any]:
            """Create and execute an operation."""
            try:
                if not isinstance(body, dict):
                    raise ValueError("Request body must be JSON object")
                
                op_type = body.get("type")
                params = body.get("params", {})
                
                if not op_type:
                    raise ValueError("Missing 'type' in request body")
                
                # Get operations manager
                ops_mgr = self.runtime.operations
                if not ops_mgr:
                    raise RuntimeError("Operations manager not available")
                
                # Create operation with admin initiator
                from core.operations import OperationInitiator, OperationInitiatorKind
                
                initiator = OperationInitiator(
                    kind=OperationInitiatorKind.ADMIN,
                    user_id=None,
                )
                
                operation = await ops_mgr.create(
                    op_type=op_type,
                    params=params,
                    initiator=initiator,
                )
                
                # Execute operation
                result = await ops_mgr.execute(operation)
                
                return result.to_dict()
            
            except ValueError as e:
                raise ValueError(str(e))
            except Exception as e:
                raise RuntimeError(f"Operation creation failed: {str(e)}")
        
        async def admin_operations_list(limit: int = 100, offset: int = 0, status: Optional[str] = None, **kwargs) -> Dict[str, Any]:
            """List operations with pagination and filtering."""
            try:
                ops_mgr = self.runtime.operations
                if not ops_mgr:
                    raise RuntimeError("Operations manager not available")
                
                ops = await ops_mgr.list(limit=limit, offset=offset)
                
                # Filter by status if provided
                if status:
                    ops = [op for op in ops if op.status.value == status]
                
                return {
                    "ok": True,
                    "operations": [op.to_dict() for op in ops],
                    "total": len(ops),
                }
            except Exception as e:
                raise RuntimeError(f"Failed to list operations: {str(e)}")
        
        async def admin_operations_get(operation_id: str, **kwargs) -> Dict[str, Any]:
            """Get operation details by ID."""
            try:
                ops_mgr = self.runtime.operations
                if not ops_mgr:
                    raise RuntimeError("Operations manager not available")
                
                op = await ops_mgr.get(operation_id)
                if not op:
                    raise ValueError(f"Operation {operation_id} not found")
                
                return op.to_dict()
            except ValueError as e:
                raise e
            except Exception as e:
                raise RuntimeError(f"Failed to get operation: {str(e)}")
        
        async def admin_operations_cancel(operation_id: str, **kwargs) -> Dict[str, Any]:
            """Cancel a pending or running operation."""
            try:
                ops_mgr = self.runtime.operations
                if not ops_mgr:
                    raise RuntimeError("Operations manager not available")
                
                op = await ops_mgr.cancel(operation_id)
                if not op:
                    raise ValueError(f"Cannot cancel operation {operation_id}")
                
                return {
                    "ok": True,
                    "operation": op.to_dict(),
                }
            except ValueError as e:
                raise e
            except Exception as e:
                raise RuntimeError(f"Failed to cancel operation: {str(e)}")
        
        async def admin_operations_retry(operation_id: str, **kwargs) -> Dict[str, Any]:
            """Retry a failed operation."""
            try:
                ops_mgr = self.runtime.operations
                if not ops_mgr:
                    raise RuntimeError("Operations manager not available")
                
                # Get original operation
                original_op = await ops_mgr.get(operation_id)
                if not original_op:
                    raise ValueError(f"Operation {operation_id} not found")
                
                # Create retry operation
                new_op = await ops_mgr.retry(operation_id)
                if not new_op:
                    raise ValueError(
                        f"Cannot retry operation {operation_id} "
                        "(not failed or error not retryable)"
                    )
                
                # Execute retry operation
                result = await ops_mgr.execute(new_op)
                
                return {
                    "ok": True,
                    "new_operation_id": result.operation_id,
                    "status": result.status.value,
                    "result": result.result,
                    "error": result.error.to_dict() if result.error else None,
                }
            except ValueError as e:
                raise e
            except Exception as e:
                raise RuntimeError(f"Failed to retry operation: {str(e)}")

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
            ("admin.v1.dashboard", admin_v1_dashboard),
            ("admin.v1.storage", admin_v1_storage),
            ("admin.v1.state", admin_v1_state),
            ("admin.v1.state_keys", admin_v1_state_keys),
            ("admin.v1.state_get", admin_v1_state_get),
            ("admin.devices.list", admin_devices_list),
            ("admin.devices.get", admin_devices_get),
            ("admin.devices.set_state", admin_devices_set_state),
            ("admin.devices.list_external", admin_devices_list_external),
            ("admin.devices.list_mappings", admin_devices_list_mappings),
            ("admin.devices.create_mapping", admin_devices_create_mapping),
            ("admin.devices.delete_mapping", admin_devices_delete_mapping),
            ("admin.devices.auto_map", admin_devices_auto_map),
            ("admin.operations.create", admin_operations_create),
            ("admin.operations.list", admin_operations_list),
            ("admin.operations.get", admin_operations_get),
            ("admin.operations.cancel", admin_operations_cancel),
            ("admin.operations.retry", admin_operations_retry),
            ("admin.v1.yandex.sync", admin_v1_yandex_sync),
            ("admin.v1.yandex.check_online", admin_v1_yandex_check_online),
            ("admin.v1.integrations", admin_v1_integrations),
            ("admin.auth.create_api_key", admin_auth_create_api_key),
            ("admin.auth.list_api_keys", admin_auth_list_api_keys),
            ("admin.auth.create_user", admin_auth_create_user),
            ("admin.auth.list_users", admin_auth_list_users),
            ("admin.auth.initialize", admin_auth_initialize),
            ("admin.auth.login", admin_auth_login),
            ("admin.auth.refresh", admin_auth_refresh),
            ("admin.auth.set_password", admin_auth_set_password),
            ("admin.auth.change_password", admin_auth_change_password),
            ("admin.auth.list_sessions", admin_auth_list_sessions),
            ("admin.auth.revoke_session", admin_auth_revoke_session),
            ("admin.auth.revoke_all_sessions", admin_auth_revoke_all_sessions),
            ("admin.auth.revoke_api_key", admin_auth_revoke_api_key),
            ("admin.auth.rotate_api_key", admin_auth_rotate_api_key),
            ("admin.auth.me", admin_auth_me),
        ]

        for name, func in service_registrations:
            try:
                # Для всего admin.* по умолчанию: admin_only (ACL на уровне ядра).
                # Исключения — публичные auth endpoints (initialize/login/refresh/me).
                admin_only = True
                if name in ("admin.auth.initialize", "admin.auth.login", "admin.auth.refresh", "admin.auth.me"):
                    admin_only = False

                if hasattr(self.runtime.service_registry, "register_with_acl"):
                    await self.runtime.service_registry.register_with_acl(name, func, admin_only=admin_only)
                else:
                    await self.runtime.service_registry.register(name, func)

                self._registered_services.append(name)
            except ValueError:
                # Already registered - skip
                continue

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
