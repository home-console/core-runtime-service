import logging
"""
Authentication middleware — FastAPI middleware для проверки авторизации.
"""

from typing import Optional
from fastapi import Request, Response

from .context import RequestContext
from .constants import RATE_LIMIT_AUTH_ATTEMPTS, RATE_LIMIT_AUTH_WINDOW
from .api_keys import validate_api_key, extract_api_key_from_header
from .sessions import validate_session, extract_session_from_cookie
from .jwt_tokens import validate_jwt_token, extract_jwt_from_header, validate_refresh_token
from .rate_limiting import rate_limit_check
from .audit import audit_log_auth_event
from .middleware_helpers import apply_rate_limiting, log_auth_result
from .contextvars import set_current_request_context
logger = logging.getLogger(__name__)


async def get_request_context(request: Request) -> Optional[RequestContext]:
    """
    Получает RequestContext из request.state.
    
    Используется в handlers для доступа к контексту авторизации.
    
    Args:
        request: FastAPI Request
    
    Returns:
        RequestContext или None если не установлен
    """
    return getattr(request.state, "auth_context", None)


async def require_auth_middleware(request: Request, call_next):
    """
    FastAPI middleware для проверки авторизации (JWT, API Key или Session).
    
    Поддерживает JWT access tokens, API keys и sessions через cookies.
    Включает rate limiting и audit logging.
    
    Приоритет:
    1. JWT access token из Authorization header (Bearer token)
    2. API Key из Authorization header (Bearer token, если не JWT)
    3. Session из Cookie (session_id)
    
    Извлекает credentials, валидирует их и сохраняет RequestContext
    в request.state.auth_context.
    
    Если credentials не переданы или невалидны, context будет None.
    Проверка прав выполняется в handlers перед вызовом service_registry.call().
    
    Args:
        request: FastAPI Request
        call_next: следующий middleware/handler
    
    Returns:
        Response
    """
    # Получаем runtime из app.state (устанавливается в ApiModule)
    runtime = getattr(request.app.state, "runtime", None)
    
    # Skip middleware для OPTIONS requests (CORS preflight)
    if request.method == "OPTIONS":
        return await call_next(request)
    
    context = None
    identifier = None
    auth_source = None
    
    # Получаем IP для rate limiting и audit
    client_ip = request.client.host if request.client else "unknown"
    
    # Проверяем, является ли это auth endpoint (требует специального rate limiting)
    # Auth endpoints: login, create_api_key, refresh_token, и другие операции аутентификации
    request_path = str(request.url.path)
    # IMPORTANT: /auth/v1/me is a read-only profile endpoint and may be called
    # frequently by the frontend (polling/hooks/retries). It must NOT be treated
    # as a brute-force surface; keep it under general API rate limiting instead.
    is_auth_endpoint = (
        request_path.startswith("/api/v1/admin/auth/")
        or request_path in (
            "/api/v1/auth/login",
            "/api/v1/auth/initialize",
            "/api/v1/auth/refresh",
            "/api/v1/auth/logout",
        )
        or "create_api_key" in request_path.lower()
    )
    
    # Rate limiting для auth endpoints (до попытки авторизации)
    # Защита от brute force атак
    if is_auth_endpoint and runtime:
        # Проверяем, включен ли rate limiting (можно отключить для разработки)
        rate_limiting_enabled = True
        if hasattr(runtime, "_config") and runtime._config:
            rate_limiting_enabled = getattr(runtime._config, "rate_limiting_enabled", True)
        
        # DEBUG MODE: allow disabling rate limiting for local development.
        # We support both DEBUG_MODE and DEBUG (legacy) flags.
        import os
        debug_mode = (
            os.getenv("DEBUG_MODE", "").lower() in ("1", "true", "yes", "on")
            or os.getenv("DEBUG", "").lower() in ("1", "true", "yes", "on")
        )
        if debug_mode:
            rate_limiting_enabled = False
        
        if rate_limiting_enabled:
            # Используем IP для rate limiting auth endpoints (защита от brute force)
            rate_limit_key = f"auth:{client_ip}"
            if not await rate_limit_check(runtime, rate_limit_key, "auth"):
                await audit_log_auth_event(
                    runtime,
                    "rate_limit_exceeded",
                    client_ip,
                    {"ip": client_ip, "path": request_path, "type": "auth_endpoint", "limit_type": "auth"},
                    success=False
                )
                response = Response(
                    content='{"detail": "Rate limit exceeded. Too many authentication attempts. Please try again later."}',
                    status_code=429,
                    media_type="application/json",
                    headers={
                        "Retry-After": str(RATE_LIMIT_AUTH_WINDOW),
                        "X-RateLimit-Limit": str(RATE_LIMIT_AUTH_ATTEMPTS),
                        "X-RateLimit-Window": str(RATE_LIMIT_AUTH_WINDOW),
                        "X-RateLimit-Type": "auth"
                    }
                )
                # Add CORS headers so browser doesn't block the response
                origin = request.headers.get("origin")
                if origin and (origin.startswith("http://localhost") or origin.startswith("http://127.0.0.1")):
                    response.headers["Access-Control-Allow-Origin"] = origin
                    response.headers["Access-Control-Allow-Credentials"] = "true"
                return response
    
    # Приоритет 0: JWT из query param ?token= (только для WebSocket — браузер не может слать header)
    jwt_token = None
    request_scope = getattr(request, "scope", {}) if request is not None else {}
    if request_scope.get("type") == "websocket":
        jwt_token = request.query_params.get("token")

    # Приоритет 1: JWT access token из Authorization header или Cookie
    # SECURITY FIX: extract_jwt_from_header проверяет формат JWT (3 части через точку)
    # Если это не JWT, функция вернёт None и мы перейдём к проверке API key
    if not jwt_token:
        jwt_token = extract_jwt_from_header(request)
    jwt_from_cookie = False
    
    # Если токен не в header, проверяем cookie
    if not jwt_token:
        jwt_token = request.cookies.get("access_token")
        jwt_from_cookie = bool(jwt_token)
    # Убрано избыточное логирование рутинных операций
    
    if jwt_token and runtime:
        try:
            context = await validate_jwt_token(runtime, jwt_token)
            if context:
                # Убрано избыточное логирование успешной валидации
                identifier = context.user_id or context.subject or "unknown"
                auth_source = "jwt"
                
                # Применяем rate limiting для API запросов (не для auth endpoints)
                rate_limit_response = await apply_rate_limiting(
                    runtime, context, identifier, auth_source, client_ip, str(request.url.path), is_auth_endpoint, request
                )
                if rate_limit_response:
                    return rate_limit_response
            else:
                # Убрано избыточное логирование для нормального fallback на API key
                pass
        except Exception as e:
            # JWT невалиден - переходим к проверке API key
            # Логируем только для не-auth endpoints, чтобы не засорять логи
            if not is_auth_endpoint and runtime:
                try:
                    await runtime.service_registry.call(
                        "logger.log",
                        level="warning",
                        message="JWT validation failed, will try API key",
                        module="auth",
                        error=str(e),
                        path=str(request.url.path)
                    )
                except Exception:
                    logger.warning("Unhandled exception", exc_info=True)
            context = None
    
    # Приоритет 2: API Key из Authorization header (если JWT не сработал или не найден)
    if context is None:
        api_key = extract_api_key_from_header(request)
        if api_key and runtime:
            try:
                context = await validate_api_key(runtime, api_key)
                if context:
                    identifier = api_key
                    auth_source = "api_key"
                    
                    # Применяем rate limiting для API запросов (не для auth endpoints)
                    rate_limit_response = await apply_rate_limiting(
                        runtime, context, identifier, auth_source, client_ip, str(request.url.path), is_auth_endpoint, request
                    )
                    if rate_limit_response:
                        return rate_limit_response
            except Exception:
                logger.debug("middleware.require_auth_middleware: error (using fallback value)", exc_info=True)
                context = None
    
    # Приоритет 3: Session из Cookie (если JWT и API Key не сработали)
    if context is None:
        session_id = extract_session_from_cookie(request)
        if session_id and runtime:
            try:
                context = await validate_session(runtime, session_id)
                identifier = session_id
                auth_source = "session"
                
                # Применяем rate limiting для API запросов (не для auth endpoints)
                rate_limit_response = await apply_rate_limiting(
                    runtime, context, identifier, auth_source, client_ip, str(request.url.path), is_auth_endpoint, request
                )
                if rate_limit_response:
                    return rate_limit_response
            except Exception:
                logger.debug("middleware.require_auth_middleware: error (using fallback value)", exc_info=True)
                context = None

    # Приоритет 4: refresh_token cookie для POST /api/v1/auth/refresh (восстановление сессии после перезагрузки страницы)
    # Access token хранится только в памяти — при F5 он теряется; refresh_token в httpOnly cookie — по нему восстанавливаем контекст
    if context is None and runtime and "/api/v1/auth/refresh" in request_path:
        refresh_token = request.cookies.get("refresh_token")
        if refresh_token:
            try:
                token_data = await validate_refresh_token(runtime, refresh_token)
                if token_data and isinstance(token_data, dict):
                    context = {
                        "user_id": token_data.get("user_id"),
                        "client_ip": token_data.get("client_ip") or client_ip,
                        "user_agent": token_data.get("user_agent") or request.headers.get("user-agent"),
                    }
                    if context.get("user_id"):
                        identifier = context["user_id"]
                        auth_source = "refresh_token"
            except Exception:
                logger.debug("middleware.require_auth_middleware: error (using fallback value)", exc_info=True)
                context = None

    # CSRF protection (только для cookie-based auth, только для state-changing методов)
    # Если авторизация идёт через Authorization header (api_key/jwt header), CSRF не нужен.
    if runtime and context is not None:
        cfg = getattr(runtime, "_config", None)
        csrf_enabled = getattr(cfg, "csrf_enabled", True) if cfg is not None else True
        if csrf_enabled:
            # Some tests use a lightweight MockRequest without `method` attribute.
            # Safely fall back to "GET" when missing.
            method = getattr(request, "method", None)
            if method is None:
                # Try Starlette-style scope if available
                try:
                    method = request.scope.get("method") if hasattr(request, "scope") else "GET"
                except Exception:
                    logger.debug("middleware.require_auth_middleware: error (using fallback value)", exc_info=True)
                    method = "GET"
            unsafe_method = str(method).upper() in ("POST", "PUT", "PATCH", "DELETE")
            cookie_based = (auth_source == "session") or (auth_source == "jwt" and jwt_from_cookie)
            if unsafe_method and cookie_based and not is_auth_endpoint:
                csrf_cookie_name = getattr(cfg, "csrf_cookie_name", "csrf_token") if cfg is not None else "csrf_token"
                csrf_header_name = getattr(cfg, "csrf_header_name", "X-CSRF-Token") if cfg is not None else "X-CSRF-Token"

                csrf_cookie = request.cookies.get(csrf_cookie_name)
                csrf_header = request.headers.get(csrf_header_name)

                # Требуем double-submit token: cookie == header
                if not csrf_cookie or not csrf_header or csrf_cookie != csrf_header:
                    return Response(
                        content='{"detail": "CSRF token missing or invalid"}',
                        status_code=403,
                        media_type="application/json",
                        headers={"X-CSRF-Required": "true"}
                    )
    
    # Audit logging
    # identifier может быть не установлен, если ни один способ авторизации не сработал
    if identifier is None:
        identifier = "unknown"
    if auth_source is None:
        auth_source = "none"
    await log_auth_result(
        runtime,
        context,
        identifier,
        auth_source,
        client_ip,
        str(request.url.path),
        request.headers.get("user-agent")
    )
    
    # Сохраняем context в request.state
    request.state.auth_context = context

    # Пробрасываем context через ContextVar для доменных сервисов
    set_current_request_context(context)

    try:
        # Продолжаем обработку запроса
        response = await call_next(request)
        return response
    finally:
        # Очищаем ContextVar чтобы не протекало между запросами
        set_current_request_context(None)
