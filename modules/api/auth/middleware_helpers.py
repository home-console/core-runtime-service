"""
Middleware helpers — общие функции для rate limiting и audit logging.
"""

from typing import Any, Optional
from fastapi import Response

from .context import RequestContext
from .constants import RATE_LIMIT_API_REQUESTS, RATE_LIMIT_API_WINDOW
from .rate_limiting import rate_limit_check
from .audit import audit_log_auth_event


async def apply_rate_limiting(
    runtime: Any,
    context: Optional[RequestContext],
    identifier: str,
    auth_source: str,
    client_ip: str,
    request_path: str,
    is_auth_endpoint: bool
) -> Optional[Response]:
    """
    Применяет rate limiting для авторизованного запроса.
    
    Args:
        runtime: экземпляр CoreRuntime
        context: RequestContext или None
        identifier: идентификатор для rate limiting (user_id, api_key, session_id)
        auth_source: источник авторизации ("jwt", "api_key", "session")
        client_ip: IP адрес клиента
        request_path: путь запроса
        is_auth_endpoint: является ли это auth endpoint
    
    Returns:
        Response с 429 если лимит превышен, None если всё OK
    """
    if not context or is_auth_endpoint:
        return None
    
    # Формируем ключ для rate limiting в зависимости от источника
    if not identifier:
        return None  # Не можем применить rate limiting без идентификатора
    
    if auth_source == "jwt":
        rate_limit_key = f"api:jwt:{context.user_id or 'unknown'}"
    elif auth_source == "api_key":
        rate_limit_key = f"api:{identifier[:16]}"
    elif auth_source == "session":
        rate_limit_key = f"api:{identifier[:16]}"
    else:
        return None
    
    if not await rate_limit_check(runtime, rate_limit_key, "api"):
        # Превышен лимит API запросов
        safe_identifier = identifier[:16] + "..." if identifier and len(identifier) > 16 else (identifier or "unknown")
        await audit_log_auth_event(
            runtime,
            "rate_limit_exceeded",
            safe_identifier,
            {
                "ip": client_ip,
                "path": request_path,
                "type": auth_source,
                "limit_type": "api"
            },
            success=False
        )
        return Response(
            content='{"detail": "Rate limit exceeded. Too many requests. Please try again later."}',
            status_code=429,
            media_type="application/json",
            headers={
                "Retry-After": "60",
                "X-RateLimit-Limit": str(RATE_LIMIT_API_REQUESTS),
                "X-RateLimit-Window": str(RATE_LIMIT_API_WINDOW)
            }
        )
    
    return None


async def log_auth_result(
    runtime: Any,
    context: Optional[RequestContext],
    identifier: Optional[str],
    auth_source: Optional[str],
    client_ip: str,
    request_path: str,
    user_agent: Optional[str]
) -> None:
    """
    Логирует результат авторизации для audit.
    
    Args:
        runtime: экземпляр CoreRuntime
        context: RequestContext или None
        identifier: идентификатор (user_id, api_key, session_id)
        auth_source: источник авторизации ("jwt", "api_key", "session")
        client_ip: IP адрес клиента
        request_path: путь запроса
        user_agent: User-Agent заголовок
    """
    if not identifier:
        return
    
    safe_identifier = identifier[:16] + "..." if identifier and len(identifier) > 16 else (identifier or "unknown")
    await audit_log_auth_event(
        runtime,
        "auth_success" if context else "auth_failure",
        safe_identifier,
        {
            "ip": client_ip,
            "path": request_path,
            "source": auth_source or "unknown",
            "user_agent": (user_agent or "unknown")[:128]
        },
        success=(context is not None)
    )
