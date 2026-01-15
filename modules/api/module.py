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
import threading
import asyncio
import re
import inspect

from fastapi import FastAPI, Request, Response, HTTPException, Path, Body, Depends
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
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        # ВАЖНО: Порядок выполнения middleware в FastAPI обратный порядку добавления
        # Последний добавленный выполняется первым
        
        # Добавляем auth middleware (boundary-layer) - выполнится вторым
        self.app.middleware("http")(require_auth_middleware)
        
        # Добавляем admin access middleware ПОСЛЕДНИМ, чтобы выполнился ПЕРВЫМ
        # Это блокирует доступ к /admin/* из публичного интернета
        # Выполнится первым (проверка IP до проверки авторизации)
        self.app.middleware("http")(admin_access_middleware)
        
        # Mount monitoring module
        self.monitoring = MonitoringModule(runtime=self.runtime)
        self.app.include_router(self.monitoring.router, prefix="/monitor", tags=["monitoring"])

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

        for ep in endpoints:
            def make_handler(endpoint):
                async def handler(
                    request: Request,
                    response: Response,
                    body: Dict[str, Any] | None = Body(None) if endpoint.method in ["POST", "PUT", "PATCH"] else None
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
                    # Для devices.get и devices.set_state - получаем device и проверяем ownership/shared
                    if endpoint.service in ["devices.get", "devices.set_state"]:
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

                    if not await self.runtime.service_registry.has_service(endpoint.service):
                        raise HTTPException(status_code=404, detail="service not found")

                    try:
                        # Вызов сервиса - CoreRuntime и доменные модули НЕ знают про auth
                        result = await self.runtime.service_registry.call(endpoint.service, **params)
                    except Exception as e:
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
                import re
                path_params = re.findall(r'\{(\w+)\}', endpoint.path)
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

        config = uvicorn.Config(self.app, host="127.0.0.1", port=8000, log_level="info")
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
