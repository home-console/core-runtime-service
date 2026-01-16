"""
Authentication middleware — FastAPI middleware для проверки авторизации.
"""

from typing import Optional
from fastapi import Request, Response

from .context import RequestContext
from .constants import RATE_LIMIT_AUTH_ATTEMPTS, RATE_LIMIT_AUTH_WINDOW
from .api_keys import validate_api_key, extract_api_key_from_header
from .sessions import validate_session, extract_session_from_cookie
from .jwt_tokens import validate_jwt_token, extract_jwt_from_header
from .rate_limiting import rate_limit_check
from .audit import audit_log_auth_event
from .middleware_helpers import apply_rate_limiting, log_auth_result


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
    
    context = None
    identifier = None
    auth_source = None
    
    # Получаем IP для rate limiting и audit
    client_ip = request.client.host if request.client else "unknown"
    
    # Проверяем, является ли это auth endpoint (требует специального rate limiting)
    is_auth_endpoint = str(request.url.path).startswith("/admin/auth/")
    
    # Rate limiting для auth endpoints (до попытки авторизации)
    if is_auth_endpoint and runtime:
        rate_limit_key = f"auth:{client_ip}"
        if not await rate_limit_check(runtime, rate_limit_key, "auth"):
            await audit_log_auth_event(
                runtime,
                "rate_limit_exceeded",
                client_ip,
                {"ip": client_ip, "path": str(request.url.path), "type": "auth_endpoint", "limit_type": "auth"},
                success=False
            )
            return Response(
                content='{"detail": "Rate limit exceeded. Too many authentication attempts. Please try again later."}',
                status_code=429,
                media_type="application/json",
                headers={
                    "Retry-After": "60",
                    "X-RateLimit-Limit": str(RATE_LIMIT_AUTH_ATTEMPTS),
                    "X-RateLimit-Window": str(RATE_LIMIT_AUTH_WINDOW)
                }
            )
    
    # Приоритет 1: JWT access token из Authorization header или Cookie
    # SECURITY FIX: extract_jwt_from_header проверяет формат JWT (3 части через точку)
    # Если это не JWT, функция вернёт None и мы перейдём к проверке API key
    jwt_token = extract_jwt_from_header(request)
    
    # Если токен не в header, проверяем cookie
    if not jwt_token:
        jwt_token = request.cookies.get("access_token")
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
                    runtime, context, identifier, auth_source, client_ip, str(request.url.path), is_auth_endpoint
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
                    pass
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
                        runtime, context, identifier, auth_source, client_ip, str(request.url.path), is_auth_endpoint
                    )
                    if rate_limit_response:
                        return rate_limit_response
            except Exception:
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
                    runtime, context, identifier, auth_source, client_ip, str(request.url.path), is_auth_endpoint
                )
                if rate_limit_response:
                    return rate_limit_response
            except Exception:
                context = None
    
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
    
    # Продолжаем обработку запроса
    response = await call_next(request)
    return response
