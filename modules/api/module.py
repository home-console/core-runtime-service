"""
ApiModule — встроенный модуль HTTP API Gateway.

Автоматически проксирует HTTP-запросы на runtime-сервисы на основе HttpRegistry.

API Key Authentication:
- Проверка авторизации выполняется на boundary-layer (HTTP)
- RequestContext передаётся через request.state
- Проверка scopes перед вызовом service_registry.call()
- CoreRuntime и доменные модули НЕ знают про auth
"""

from typing import Any, Dict
import os
import threading
import asyncio
import re
import inspect

from fastapi import FastAPI, Request, Response, HTTPException, Path, Body, Depends, WebSocket, WebSocketDisconnect
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.openapi.utils import get_openapi
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from core.runtime_module import RuntimeModule
from modules.api.auth import (
    require_auth_middleware,
    get_request_context,
)
from modules.api.authz import require as authz_require, AuthorizationError
from modules.api.admin_access_middleware import admin_access_middleware
from modules.monitoring import MonitoringModule
from modules.api.validation_models import validate_body_for_service


class ApiModule(RuntimeModule):
    """
    Модуль HTTP API Gateway.
    
    Автоматически создаёт HTTP endpoints на основе зарегистрированных
    контрактов в runtime.http и проксирует запросы в runtime-сервисы.
    """

    @property
    def name(self) -> str:
        """Уникальное имя модуля."""
        return "api"

    def __init__(self, runtime: Any):
        """Инициализация модуля."""
        super().__init__(runtime)
        self.app: FastAPI | None = None
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self.monitoring: MonitoringModule | None = None

    async def register(self) -> None:
        """
        Регистрация модуля в CoreRuntime.
        
        Создаёт FastAPI приложение. Маршруты регистрируются при старте,
        чтобы все модули и плагины успели внести свои контракты в runtime.http.
        """
        self.app = FastAPI(
            title="Home Console API",
            version="0.1.0",
            openapi_url="/openapi.json"
        )
        
        # Сохраняем runtime в app.state для доступа из middleware
        self.app.state.runtime = self.runtime
        
        # Добавляем CORS middleware для работы с frontend
        # В production задаётся через Config.cors_allowed_origins / env RUNTIME_CORS_ALLOWED_ORIGINS
        cors_allowed = None
        is_dev = False
        env = "development"
        try:
            cfg = getattr(self.runtime, "_config", None)
            if cfg:
                cors_allowed = getattr(cfg, "cors_allowed_origins", None)
                is_dev = getattr(cfg, "env", "production") == "development"
            if cfg:
                cors_allowed = getattr(cfg, "cors_allowed_origins", None)
                env = getattr(cfg, "env", "development")
        except Exception:
            cors_allowed = None
            is_dev = True
        cors_kw: Dict[str, Any] = {
            "allow_origins": cors_allowed or ["http://localhost:3000", "http://127.0.0.1:3000"],
            "allow_credentials": True,
            "allow_methods": ["*"],
            "allow_headers": ["*"],
        }
        # В dev разрешаем любой порт на localhost (Flutter web, Vite и т.д.)
        if is_dev:
            cors_kw["allow_origin_regex"] = r"^http://(localhost|127\.0\.0\.1)(:\d+)?$"
        self.app.add_middleware(CORSMiddleware, **cors_kw)
        
        # ВАЖНО: Порядок выполнения middleware в FastAPI обратный порядку добавления
        # Последний добавленный выполняется первым
        
        # Добавляем request logger middleware (выполнится предпоследним)
        # Это нужно для того, чтобы он мог перехватывать все запросы
        try:
            from modules.request_logger.middleware import request_logger_middleware
            self.app.middleware("http")(request_logger_middleware)
        except ImportError:
            # RequestLoggerModule может быть не установлен - это нормально
            pass
        
        # SECURITY P0: CSRF и rate limit — добавляем ПЕРВЫМИ, чтобы выполнились ПОСЛЕ auth
        # (в FastAPI последний добавленный middleware выполняется первым)
        try:
            from modules.api.csrf_middleware import csrf_protection_middleware, rate_limit_middleware
            self.app.middleware("http")(csrf_protection_middleware)
            self.app.middleware("http")(rate_limit_middleware)
        except ImportError:
            pass
        
        # Auth middleware — добавляем после CSRF/rate_limit, чтобы выполнился ПЕРВЫМ для запроса
        # и заполнил request.state.auth_context до проверки CSRF
        self.app.middleware("http")(require_auth_middleware)
        
        # Добавляем admin access middleware (должен выполниться раньше auth)
        # Это блокирует доступ к /admin/* из публичного интернета
        # Выполнится после security headers и до проверки авторизации
        self.app.middleware("http")(admin_access_middleware)

        # Добавляем security headers middleware ПОСЛЕДНИМ (выполнится ПЕРВЫМ)
        # Это добавляет security headers ко всем ответам, включая ранние 403/401.
        from modules.api.security_headers import security_headers_middleware
        self.app.middleware("http")(security_headers_middleware)
        
        # Mount monitoring module
        self.monitoring = MonitoringModule(runtime=self.runtime)
        self.app.include_router(self.monitoring.router, prefix="/monitor", tags=["monitoring"])
        
        # Mount request logger router (если модуль доступен)
        try:
            from modules.request_logger.router import create_request_logger_router
            request_logger_router = create_request_logger_router(self.runtime)
            self.app.include_router(request_logger_router)
        except ImportError:
            # RequestLoggerModule может быть не установлен - это нормально
            pass
        
        # Bootstrap: регистрируем минимальный набор HTTP endpoints
        # для восстановления функциональности после C1 (удаления HTTP из admin/module.py)
        try:
            from adapters.http.bootstrap import register_core_http
            register_core_http(self.runtime)
        except ImportError:
            # Bootstrap не критичен для старта
            pass

    async def start(self) -> None:
        """
        Запуск модуля.
        
        Регистрирует HTTP маршруты на основе текущего состояния HttpRegistry
        и запускает HTTP сервер.
        """
        if self.app is None:
            return
        
        # Делаем короткую паузу, чтобы модули и плагины успели зарегистрировать свои
        # HTTP-контракты в `runtime.http` до того, как мы снимем с него список.
        try:
            await asyncio.sleep(0.2)
        except Exception:
            pass

        # Регистрируем маршруты на основе текущего состояния HttpRegistry.
        endpoints = self.runtime.http.list()

        # Разделяем endpoints на API и webhook
        api_endpoints = [ep for ep in endpoints if ep.kind == "api"]
        webhook_endpoints = [ep for ep in endpoints if ep.kind == "webhook"]

        # Регистрируем API endpoints (с auth, acl, context)
        for ep in api_endpoints:
            def make_handler(endpoint):
                # Извлекаем path параметры из пути ДО определения handler
                import re
                path_params = re.findall(r'\{(\w+)\}', endpoint.path)
                
                # Создаём базовую сигнатуру handler
                # Параметры пути будут добавлены в сигнатуру ниже
                # Используем **kwargs чтобы принимать параметры пути, которые FastAPI передаёт
                async def handler(
                    request: Request,
                    response: Response,
                    body: Dict[str, Any] | None = Body(None) if endpoint.method in ["POST", "PUT", "PATCH"] else None,
                    **kwargs  # Принимаем все path параметры, которые FastAPI передаёт
                ):
                    # Получаем RequestContext из middleware (boundary-layer)
                    context = await get_request_context(request)
                    
                    # Подготавливаем resource для Resource-Based Authorization
                    resource = None
                    
                    # Специальный случай: разрешаем создание первого API key без авторизации
                    # SECURITY FIX: Используем атомарную проверку для предотвращения race condition
                    if endpoint.service == "admin.auth.create_api_key" and context is None:
                        # Проверяем, есть ли уже API keys (атомарная операция)
                        try:
                            keys = await self.runtime.storage.list_keys("auth_api_keys")
                            # Дополнительная проверка: пытаемся получить флаг создания первого ключа
                            first_key_flag = await self.runtime.storage.get("auth_config", "first_key_created")
                            if len(keys) == 0 and first_key_flag is None:
                                # Нет ключей и флаг не установлен - разрешаем создание первого
                                # Устанавливаем флаг ДО создания ключа (защита от race condition)
                                # Если флаг уже установлен другим запросом, это нормально
                                try:
                                    await self.runtime.storage.set("auth_config", "first_key_created", True)
                                    resource = {"allow_first_key": True}
                                except Exception:
                                    # Если не удалось установить флаг, проверяем ещё раз
                                    keys_retry = await self.runtime.storage.list_keys("auth_api_keys")
                                    if len(keys_retry) == 0:
                                        resource = {"allow_first_key": True}
                        except Exception:
                            pass
                    
                    # Для auth операций - передаём user_id из body или path
                    if endpoint.service in ["admin.auth.change_password", "admin.auth.set_password", 
                                           "admin.auth.revoke_all_sessions", "admin.auth.list_sessions"]:
                        # Получаем body, если ещё не получен
                        if body is None and endpoint.method in ["POST", "PUT", "PATCH"]:
                            try:
                                body = await request.json()
                            except Exception:
                                body = None
                        
                        if isinstance(body, dict):
                            user_id = body.get("user_id")
                            if user_id:
                                resource = {"user_id": user_id}
                    
                    # SECURITY FIX: Проверяем базовую авторизацию ДО получения device
                    # Это предотвращает Information Disclosure (раскрытие существования device)
                    # Исключение: публичные endpoints не требуют авторизации
                    # Публичные endpoints: доступ без авторизации (для логина, инициализации, Yandex auth UI)
                    public_endpoints = [
                        "admin.auth.me",
                        "admin.auth.initialize",
                        "admin.auth.login",
                        "admin.auth.refresh",
                        "yandex_device_auth.start",
                        "yandex_device_auth.cookies",
                        "yandex_device_auth.status",
                        "yandex_device_auth.get_session",
                        "yandex_device_auth.cancel",
                        "oauth_yandex.get_status",
                        "oauth_yandex.get_authorize_url",
                        "oauth_yandex.configure",
                        "oauth_yandex.exchange_code",
                        "oauth_yandex.clear_tokens",
                        "yandex.login.start",
                        "yandex.login.status",
                    ]
                    is_public = endpoint.service in public_endpoints
                    if not is_public:
                        try:
                            # Сначала проверяем базовые права без resource (scope-based)
                            # Передаём runtime для audit logging отказов
                            authz_require(context, endpoint.service, None, runtime=self.runtime)
                        except AuthorizationError:
                            raise HTTPException(
                                status_code=401 if context is None else 403,
                                detail="Unauthorized" if context is None else "Forbidden: insufficient permissions"
                            )
                    
                    # Только если базовая авторизация прошла, получаем device для ACL проверки
                    # Resource-Based Authorization: подготавливаем resource для проверки ACL
                    # Для devices.get, devices.set_state и product_api set_state — получаем device и проверяем ownership/shared
                    if endpoint.service in ["devices.get", "devices.set_state", "product_api.v1.devices.set_state"]:
                        device_id = request.path_params.get("id") or request.path_params.get("device_id")
                        if device_id:
                            try:
                                device = await self.runtime.service_registry.call("devices.get", device_id)
                                if isinstance(device, dict):
                                    resource = {}
                                    if "owner_id" in device:
                                        resource["owner_id"] = device["owner_id"]
                                    if "shared_with" in device:
                                        resource["shared_with"] = device["shared_with"]
                                    
                                    # Проверяем ACL (Resource-Based Authorization)
                                    try:
                                        # Передаём runtime для audit logging отказов
                                        authz_require(context, endpoint.service, resource, runtime=self.runtime)
                                    except AuthorizationError:
                                        raise HTTPException(
                                            status_code=403,
                                            detail="Forbidden: insufficient permissions for this resource"
                                        )
                            except HTTPException:
                                # Пробрасываем HTTPException (403 Forbidden)
                                raise
                            except Exception:
                                # Если device не найден, это нормально - сервис вернёт 404
                                # Не раскрываем информацию о существовании device здесь
                                pass
                    # для list_devices не используем отдельную ACL проверку здесь —
                    # enforcement делается в services.list_devices через ContextVar.
                    
                    params: Dict[str, Any] = {}
                    # path params доступны через request.path_params
                    params.update(request.path_params)
                    for k, v in request.query_params.multi_items():
                        params[k] = v
                    
                    # Используем body из параметра, если он есть, иначе пытаемся получить из request
                    # (для Swagger UI body будет в параметре, для прямых запросов - в request)
                    # Но только если body ещё не был получен выше (для auth операций)
                    if body is None and endpoint.method in ["POST", "PUT", "PATCH"]:
                        try:
                            body = await request.json()
                        except Exception:
                            body = None

                    # A03: input validation (Pydantic) для критичных endpoints
                    if body is not None and endpoint.method in ["POST", "PUT", "PATCH"]:
                        try:
                            body = validate_body_for_service(endpoint.service, body)
                        except ValueError as ve:
                            raise HTTPException(status_code=400, detail=str(ve))

                    # Передаём body отдельно от query/path params только если он не None
                    # Не мержим body в params, чтобы сохранить структуру данных
                    if body is not None:
                        params["body"] = body
                    
                    # Для auth эндпоинтов передаём request и response для установки cookies
                    if endpoint.service in ["admin.auth.login", "admin.auth.refresh"]:
                        params["request"] = request
                        params["response"] = response
                    
                    # Для admin.auth.me передаём request для получения context
                    if endpoint.service == "admin.auth.me":
                        params["request"] = request
                    
                    # Для oauth_yandex.configure распаковываем body в отдельные параметры
                    if endpoint.service == "oauth_yandex.configure" and body and isinstance(body, dict):
                        params.pop("body", None)  # Убираем body
                        params["client_id"] = body.get("client_id", "")
                        params["client_secret"] = body.get("client_secret", "")
                        params["redirect_uri"] = body.get("redirect_uri", "")
                        if "scope" in body:
                            params["scope"] = body.get("scope")
                    
                    # Для oauth_yandex.exchange_code распаковываем body в отдельные параметры
                    if endpoint.service == "oauth_yandex.exchange_code" and body and isinstance(body, dict):
                        params.pop("body", None)  # Убираем body
                        params["code"] = body.get("code", "")

                    if not await self.runtime.service_registry.has_service(endpoint.service):
                        raise HTTPException(status_code=404, detail="service not found")

                    try:
                        # Вызов сервиса - CoreRuntime и доменные модули НЕ знают про auth
                        result = await self.runtime.service_registry.call(endpoint.service, **params)
                    except Exception as e:
                        # Typed core errors -> proper HTTP mapping
                        try:
                            from core.errors import (
                                BadRequestError,
                                UnauthorizedError,
                                ForbiddenError,
                                NotFoundError,
                            )
                        except Exception:
                            BadRequestError = UnauthorizedError = ForbiddenError = NotFoundError = ()  # type: ignore

                        if BadRequestError and isinstance(e, BadRequestError):
                            raise HTTPException(status_code=400, detail=str(e))
                        if UnauthorizedError and isinstance(e, UnauthorizedError):
                            raise HTTPException(status_code=401, detail="Unauthorized")
                        if ForbiddenError and isinstance(e, ForbiddenError):
                            raise HTTPException(status_code=403, detail="Forbidden")
                        if NotFoundError and isinstance(e, NotFoundError):
                            raise HTTPException(status_code=404, detail="Not Found")

                        # Map ValueError from services to HTTP 400 (bad request)
                        if isinstance(e, ValueError):
                            raise HTTPException(status_code=400, detail=str(e))
                        raise HTTPException(status_code=500, detail=str(e))

                    return result

                # Сигнатура для правильной документации в OpenAPI
                # Извлекаем path параметры из endpoint.path
                params_sig = []
                
                # Добавляем request
                params_sig.append(
                    inspect.Parameter(
                        "request",
                        kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
                        annotation=Request,
                    )
                )
                
                # Добавляем response
                params_sig.append(
                    inspect.Parameter(
                        "response",
                        kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
                        annotation=Response,
                    )
                )
                
                # Добавляем body для POST/PUT/PATCH методов (для Swagger UI)
                # Используем Any вместо Dict, чтобы Swagger показывал JSON editor
                if endpoint.method in ["POST", "PUT", "PATCH"]:
                    params_sig.append(
                        inspect.Parameter(
                            "body",
                            kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
                            annotation=Any,
                            default=Body(None, description="Request body (JSON)"),
                        )
                    )
                
                # Извлекаем path параметры из пути (например, {id} из /admin/v1/devices/{id})
                # Используем уже извлечённые path_params из начала функции
                for param_name in path_params:
                    params_sig.append(
                        inspect.Parameter(
                            param_name,
                            kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
                            annotation=str,
                            default=Path(..., description=f"Path parameter: {param_name}"),
                        )
                    )

                handler.__signature__ = inspect.Signature(parameters=params_sig)
                return handler

            handler = make_handler(ep)
            route_name = f"{ep.method}_{ep.path}"
            # HttpRegistry теперь нормализует пути, удаляя завершающий '/'.
            # Дублирование со слэшем и без слэша больше не нужно.
            self.app.add_api_route(ep.path, handler, methods=[ep.method], name=route_name)

        # Регистрируем webhook endpoints (без auth, без ACL, минимальный context)
        for ep in webhook_endpoints:
            def make_webhook_handler(endpoint):
                async def webhook_handler(request: Request):
                    """
                    Webhook handler - minimal processing, no auth/ACL.
                    
                    Webhook endpoint:
                    - Called by external systems
                    - No authentication required
                    - No ACL checks
                    - Minimal context (just payload + headers)
                    - Directly calls service
                    """
                    try:
                        # Try to extract JSON payload
                        payload = None
                        try:
                            payload = await request.json()
                        except Exception:
                            # If no JSON, try to get raw body
                            payload = await request.body()
                        
                        # Call service - handle both sync and async
                        try:
                            result = await self.runtime.service_registry.call(
                                endpoint.service,
                                payload=payload,
                                headers=dict(request.headers),
                                raw_request=request
                            )
                        except TypeError:
                            # If service is sync, call it directly
                            result = self.runtime.service_registry.call(
                                endpoint.service,
                                payload=payload,
                                headers=dict(request.headers),
                                raw_request=request
                            )
                        
                        return {"ok": True, "result": result}
                    
                    except Exception as e:
                        import logging
                        logging.error(f"Webhook error for {endpoint.service}: {str(e)}")
                        import traceback
                        traceback.print_exc()
                        # Return error response
                        return {"ok": False, "error": str(e)}
                
                return webhook_handler
            
            webhook_handler = make_webhook_handler(ep)
            route_name = f"webhook_{ep.method}_{ep.path}"
            # Регистрируем webhook как API route (FastAPI будет знать о нём)
            # Но он НЕ будет показан в OpenAPI /docs потому что мы отфильтруем его при генерации schema
            self.app.add_api_route(ep.path, webhook_handler, methods=[ep.method], name=route_name, include_in_schema=False)

        # Регистрируем WebSocket endpoints
        ws_endpoints = [ep for ep in endpoints if ep.websocket]
        for ep in ws_endpoints:
            def make_ws_handler(endpoint):
                """Фабрика для создания WebSocket handler с правильным биндингом."""
                async def ws_handler(websocket: WebSocket):
                    """
                    WebSocket handler — поддерживает долгоживущие соединения.
                    
                    WebSocket endpoint:
                    - Accept connection
                    - Call service with websocket object
                    - Service handle message exchange
                    - Connection closes when handler completes
                    """
                    await websocket.accept()
                    try:
                        # Вызываем сервис с объектом WebSocket
                        # Сервис отвечает за корректное завершение соединения
                        await self.runtime.service_registry.call(
                            endpoint.service,
                            websocket=websocket
                        )
                    except WebSocketDisconnect:
                        # Client disconnected normally
                        pass
                    except Exception as e:
                        import logging
                        logging.error(f"WebSocket error for {endpoint.service}: {str(e)}")
                        import traceback
                        traceback.print_exc()
                        try:
                            await websocket.close(code=1011, reason="Internal Server Error")
                        except Exception:
                            pass
                
                return ws_handler
            
            ws_handler = make_ws_handler(ep)
            route_name = f"ws_{ep.path.replace('/', '_').lstrip('_')}"
            # Регистрируем WebSocket маршрут
            # include_in_schema=False потому что WebSocket не в OpenAPI 3.0.x (еще)
            self.app.websocket(ep.path, name=route_name)(ws_handler)

        # Настраиваем OpenAPI схему ПОСЛЕ регистрации всех routes
        def custom_openapi():
            if self.app.openapi_schema:
                return self.app.openapi_schema
            openapi_schema = get_openapi(
                title="Home Console API",
                version="0.1.0",
                description="Home Console Core Runtime API",
                routes=self.app.routes,
            )
            # Добавляем Security схему для Bearer token
            if "components" not in openapi_schema:
                openapi_schema["components"] = {}
            openapi_schema["components"]["securitySchemes"] = {
                "BearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "API Key",
                    "description": "Enter your API key (without 'Bearer' prefix)"
                }
            }
            # Применяем security ко всем endpoints
            for path, path_item in openapi_schema.get("paths", {}).items():
                for method in path_item.keys():
                    if method.lower() in ["get", "post", "put", "delete", "patch"]:
                        if "security" not in path_item[method]:
                            path_item[method]["security"] = [{"BearerAuth": []}]
            self.app.openapi_schema = openapi_schema
            return openapi_schema
        
        # Переопределяем openapi для добавления security
        self.app.openapi = custom_openapi

        # Уровень логирования uvicorn: можно изменить через LOG_LEVEL или по умолчанию warning
        # Отключаем access log для uvicorn (используем наш middleware для логирования)
        uvicorn_log_level = os.getenv("UVICORN_LOG_LEVEL", "warning")
        api_host = os.getenv("API_HOST", "0.0.0.0")
        api_port = int(os.getenv("API_PORT", "8000"))
        config = uvicorn.Config(
            self.app,
            host=api_host,
            port=api_port, 
            log_level=uvicorn_log_level,
            access_log=False  # Отключаем access log uvicorn, используем наш middleware
        )
        server = uvicorn.Server(config)
        self._server = server

        def run_server():
            # Запуск сервера в отдельном потоке
            try:
                server.run()
            except SystemExit:
                # uvicorn вызывает SystemExit(1) при ошибке привязки порта;
                # подавляем исключение в потоке и логируем
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(
                        self.runtime.service_registry.call(
                            "logger.log",
                            level="warning",
                            message="uvicorn exited during startup (port may be in use)",
                            module="api"
                        )
                    )
                    loop.close()
                except Exception:
                    pass
                return
            except Exception as e:
                # Общий защитный fallback — логируем и завершаем поток.
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(
                        self.runtime.service_registry.call(
                            "logger.log",
                            level="error",
                            message=f"server run error: {e}",
                            module="api"
                        )
                    )
                    loop.close()
                except Exception:
                    pass
                return

        self._thread = threading.Thread(target=run_server, daemon=True)
        self._thread.start()

    async def stop(self) -> None:
        """
        Остановка модуля.
        
        Останавливает HTTP сервер.
        """
        # Останавливаем сервер, не блокируя event loop
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            # join в отдельном потоке, чтобы не блокировать async loop
            await asyncio.to_thread(self._thread.join, timeout=1)
