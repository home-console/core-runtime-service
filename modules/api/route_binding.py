"""
Route binding: attaches HttpRegistry endpoints to a FastAPI app.

Used by Runtime after modules and plugins have registered routes.
Runtime owns the app; this module only provides bind_routes(runtime, app).

REFACTORING: Проблема 6 - упрощённый binding, использующий декларативную конфигурацию
и доменные адаптеры вместо хардкода доменной логики.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
import re
import inspect

from fastapi import Request, Response, HTTPException, Path, Body, WebSocket, WebSocketDisconnect
from fastapi.openapi.utils import get_openapi

from modules.api.auth import get_request_context
from modules.api.authz import require as authz_require, AuthorizationError
from modules.api.validation_models import validate_body_for_service
from modules.api.domain_adapters import get_domain_adapter


def bind_routes(runtime: Any, app: Any) -> None:
    """
    Bind all endpoints from runtime.http to the FastAPI app.
    Must be called AFTER module_manager.start_all() and plugin_manager.start_all().
    """
    endpoints = runtime.http.list()
    # WebSocket endpoints (method=None) не должны попадать в api/webhook — только в ws_endpoints
    api_endpoints = [ep for ep in endpoints if ep.kind == "api" and not ep.websocket]
    webhook_endpoints = [ep for ep in endpoints if ep.kind == "webhook" and not ep.websocket]
    ws_endpoints = [ep for ep in endpoints if ep.websocket]

    for ep in api_endpoints:
        handler = _make_api_handler(runtime, ep)
        route_name = f"{ep.method}_{ep.path}"
        app.add_api_route(ep.path, handler, methods=[ep.method], name=route_name)

    for ep in webhook_endpoints:
        handler = _make_webhook_handler(runtime, ep)
        route_name = f"webhook_{ep.method}_{ep.path}"
        app.add_api_route(ep.path, handler, methods=[ep.method], name=route_name, include_in_schema=False)

    for ep in ws_endpoints:
        handler = _make_ws_handler(runtime, ep)
        route_name = f"ws_{ep.path.replace('/', '_').lstrip('_')}"
        app.websocket(ep.path, name=route_name)(handler)

    _install_openapi_schema(app)


def _make_api_handler(runtime: Any, endpoint: Any):
    """
    Создать FastAPI handler для API endpoint.
    
    REFACTORING: Проблема 6 - использует декларативную конфигурацию из endpoint.auth_config
    и доменные адаптеры вместо хардкода доменной логики.
    """
    path_params = re.findall(r'\{(\w+)\}', endpoint.path)

    async def handler(
        request: Request,
        response: Response,
        body: Dict[str, Any] | None = Body(None) if endpoint.method in ["POST", "PUT", "PATCH"] else None,
        **kwargs: Any
    ):
        # Получаем контекст запроса
        context = await get_request_context(request)
        
        # REFACTORING: Проблема 6 - используем декларативную конфигурацию auth
        auth_config = endpoint.auth_config
        is_public = auth_config.public if auth_config else False
        
        # DEBUG: логирование для публичных эндпоинтов
        if "bootstrap" in endpoint.path or "initialize" in endpoint.path:
            debug_runtime = getattr(request.app.state, "runtime", None) or runtime
            if debug_runtime and hasattr(debug_runtime, "logger"):
                try:
                    await debug_runtime.service_registry.call(
                        "logger.log",
                        level="info",
                        message=f"[ROUTE_BINDING] {endpoint.service} auth_config={auth_config} is_public={is_public}",
                        component="auth_debug"
                    )
                except Exception:
                    pass
        
        # Если не указана декларативная конфигурация, используем fallback на старую логику
        # для обратной совместимости
        if auth_config is None:
            # Fallback: определяем публичные endpoints по списку (legacy)
            public_endpoints = [
                "auth.bootstrap", "auth.dev_credentials", "auth.initialize", "auth.login", "auth.refresh", "auth.me",
                "admin.auth.me", "admin.auth.initialize", "admin.auth.login", "admin.auth.refresh",
                "yandex_device_auth.start", "yandex_device_auth.cookies", "yandex_device_auth.status",
                "yandex_device_auth.get_session", "yandex_device_auth.cancel",
                "oauth_yandex.get_status", "oauth_yandex.get_authorize_url", "oauth_yandex.configure",
                "oauth_yandex.exchange_code", "oauth_yandex.clear_tokens",
                "yandex.login.start", "yandex.login.status",
            ]
            is_public = endpoint.service in public_endpoints
        
        # Авторизация: проверяем доступ к действию
        resource: Optional[Dict[str, Any]] = None
        
        if not is_public:
            # REFACTORING: Проблема 6 - используем доменный адаптер для получения resource
            if auth_config and auth_config.resource_adapter:
                adapter = get_domain_adapter(auth_config.resource_adapter)
                if adapter:
                    # Читаем body заранее для auth adapter
                    temp_body = body
                    if temp_body is None and endpoint.method in ["POST", "PUT", "PATCH"]:
                        try:
                            temp_body = await request.json()
                        except Exception:
                            temp_body = None
                    
                    resource = await adapter.extract_resource(
                        request=request,
                        service_name=endpoint.service,
                        runtime=runtime,
                        context=context,
                        body=temp_body
                    )
            
            # Если не использовали адаптер, пробуем legacy fallback для auth endpoints
            if resource is None and endpoint.service == "admin.auth.create_api_key" and context is None:
                try:
                    keys = await runtime.storage.list_keys("auth_api_keys")
                    first_key_flag = await runtime.storage.get("auth_config", "first_key_created")
                    if len(keys) == 0 and first_key_flag is None:
                        try:
                            await runtime.storage.set("auth_config", "first_key_created", True)
                            resource = {"allow_first_key": True}
                        except Exception:
                            keys_retry = await runtime.storage.list_keys("auth_api_keys")
                            if len(keys_retry) == 0:
                                resource = {"allow_first_key": True}
                except Exception:
                    pass
            
            # Проверяем авторизацию на действие
            try:
                authz_require(context, endpoint.service, resource, runtime=runtime)
            except AuthorizationError:
                raise HTTPException(
                    status_code=401 if context is None else 403,
                    detail="Unauthorized" if context is None else "Forbidden: insufficient permissions"
                )
        
        # REFACTORING: Проблема 6 - используем доменный адаптер для resource check
        if auth_config and auth_config.requires_resource_check:
            if auth_config.resource_adapter:
                adapter = get_domain_adapter(auth_config.resource_adapter)
                if adapter:
                    # Читаем body заранее для адаптера
                    temp_body = body
                    if temp_body is None and endpoint.method in ["POST", "PUT", "PATCH"]:
                        try:
                            temp_body = await request.json()
                        except Exception:
                            temp_body = None
                    
                    # Получаем resource через адаптер
                    extracted_resource = await adapter.extract_resource(
                        request=request,
                        service_name=endpoint.service,
                        runtime=runtime,
                        context=context,
                        body=temp_body
                    )
                    if extracted_resource:
                        resource = extracted_resource
                        # Проверяем доступ к ресурсу
                        try:
                            authz_require(context, endpoint.service, resource, runtime=runtime)
                        except AuthorizationError:
                            raise HTTPException(
                                status_code=403,
                                detail="Forbidden: insufficient permissions for this resource"
                            )
        
        # Извлекаем параметры для вызова сервиса
        path_params_dict = dict(request.path_params)
        query_params_dict = {k: v for k, v in request.query_params.multi_items()}
        
        # Если body не передан, пытаемся прочитать из request
        if body is None and endpoint.method in ["POST", "PUT", "PATCH"]:
            try:
                body = await request.json()
            except Exception:
                body = None
        
        # REFACTORING: Проблема 6 - используем доменный адаптер для маппинга параметров
        if auth_config and auth_config.resource_adapter:
            adapter = get_domain_adapter(auth_config.resource_adapter)
            if adapter:
                params = await adapter.extract_params(
                    request=request,
                    body=body,
                    path_params=path_params_dict,
                    query_params=query_params_dict,
                    service_name=endpoint.service,
                    response=response
                )
            else:
                # Fallback: стандартный маппинг
                params: Dict[str, Any] = {}
                params.update(path_params_dict)
                params.update(query_params_dict)
                if body is not None:
                    params["body"] = body
        else:
            # Стандартный маппинг параметров
            params: Dict[str, Any] = {}
            params.update(path_params_dict)
            params.update(query_params_dict)
            
            # Валидация body
            if body is not None and endpoint.method in ["POST", "PUT", "PATCH"]:
                try:
                    body = validate_body_for_service(endpoint.service, body)
                except ValueError as ve:
                    raise HTTPException(status_code=400, detail=str(ve))
            
            if body is not None:
                params["body"] = body
            
            # OAuth endpoints need special parameter extraction
            if endpoint.service == "oauth_yandex.configure" and body and isinstance(body, dict):
                params.pop("body", None)
                params["client_id"] = body.get("client_id", "")
                params["client_secret"] = body.get("client_secret", "")
                params["redirect_uri"] = body.get("redirect_uri", "")
                if "scope" in body:
                    params["scope"] = body.get("scope")
            elif endpoint.service == "oauth_yandex.exchange_code" and body and isinstance(body, dict):
                params.pop("body", None)
                params["code"] = body.get("code", "")
        
        # Проверяем существование сервиса
        if not await runtime.service_registry.has_service(endpoint.service):
            raise HTTPException(status_code=404, detail="service not found")
        
        # Вызываем сервис
        try:
            result = await runtime.service_registry.call(endpoint.service, **params)
        except Exception as e:
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
            if isinstance(e, ValueError):
                raise HTTPException(status_code=400, detail=str(e))
            raise HTTPException(status_code=500, detail=str(e))

        # Apply cookies from contextvars (set by service layer)
        try:
            from core.auth_contextvars import get_response_cookies
            cookies = get_response_cookies()
            if cookies:
                for cookie_key, cookie_data in cookies.items():
                    max_age = cookie_data.get("max_age")
                    httponly = cookie_data.get("httponly", False)
                    secure = cookie_data.get("secure", False)
                    samesite = cookie_data.get("samesite", "Lax")
                    path = cookie_data.get("path", "/")
                    value = cookie_data.get("value", "")
                    
                    # If value is empty or max_age is 0, delete the cookie
                    if value == "" or max_age == 0:
                        response.delete_cookie(key=cookie_key, path=path)
                    else:
                        response.set_cookie(
                            key=cookie_key,
                            value=value,
                            max_age=max_age,
                            httponly=httponly,
                            secure=secure,
                            samesite=samesite,
                            path=path
                        )
        except Exception:
            # If cookie setup fails, don't break the response
            pass

        return result

    # Формируем сигнатуру handler'а для FastAPI
    params_sig = [
        inspect.Parameter("request", kind=inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=Request),
        inspect.Parameter("response", kind=inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=Response),
    ]
    if endpoint.method in ["POST", "PUT", "PATCH"]:
        params_sig.append(
            inspect.Parameter("body", kind=inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=Any,
                              default=Body(None, description="Request body (JSON)"))
        )
    for param_name in path_params:
        params_sig.append(
            inspect.Parameter(param_name, kind=inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=str,
                              default=Path(..., description=f"Path parameter: {param_name}"))
        )
    handler.__signature__ = inspect.Signature(parameters=params_sig)
    return handler


def _make_webhook_handler(runtime: Any, endpoint: Any):
    async def webhook_handler(request: Request):
        try:
            payload = None
            try:
                payload = await request.json()
            except Exception:
                payload = await request.body()
            try:
                result = await runtime.service_registry.call(
                    endpoint.service,
                    payload=payload,
                    headers=dict(request.headers),
                    raw_request=request
                )
            except TypeError:
                result = runtime.service_registry.call(
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
            return {"ok": False, "error": str(e)}
    return webhook_handler


def _make_ws_handler(runtime: Any, endpoint: Any):
    async def ws_handler(websocket: WebSocket):
        await websocket.accept()
        try:
            # WebSocket‑хендлеры по определению долгоживущие, поэтому вызываем
            # сервис без default_timeout, иначе соединение будет рваться по таймауту.
            if hasattr(runtime.service_registry, "call_without_timeout"):
                await runtime.service_registry.call_without_timeout(endpoint.service, websocket=websocket)
            else:
                await runtime.service_registry.call(endpoint.service, websocket=websocket)
        except WebSocketDisconnect:
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


def _install_openapi_schema(app: Any) -> None:
    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        openapi_schema = get_openapi(
            title="Home Console API",
            version="0.1.0",
            description="Home Console Core Runtime API",
            routes=app.routes,
        )
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
        for path, path_item in openapi_schema.get("paths", {}).items():
            for method in path_item.keys():
                if method.lower() in ["get", "post", "put", "delete", "patch"]:
                    if "security" not in path_item[method]:
                        path_item[method]["security"] = [{"BearerAuth": []}]
        app.openapi_schema = openapi_schema
        return openapi_schema
    app.openapi = custom_openapi
