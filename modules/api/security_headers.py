"""
Security headers middleware — добавляет security headers для защиты от атак.

Реализует:
- X-Content-Type-Options: nosniff
- X-Frame-Options: DENY (защита от clickjacking)
- X-XSS-Protection: 1; mode=block
- Strict-Transport-Security (HSTS) для HTTPS
- Content-Security-Policy (базовая)
- Referrer-Policy
"""

from fastapi import Request, Response
from typing import Callable, Any, Optional


async def security_headers_middleware(request: Request, call_next: Callable) -> Response:
    """
    Middleware для добавления security headers.
    
    Защищает от:
    - Clickjacking (X-Frame-Options)
    - MIME type sniffing (X-Content-Type-Options)
    - XSS атак (X-XSS-Protection, CSP)
    - Man-in-the-middle (HSTS)
    
    Args:
        request: FastAPI Request
        call_next: следующий middleware/handler
    
    Returns:
        Response с добавленными security headers
    """
    response = await call_next(request)

    # Получаем runtime/config, если доступны (чтобы различать dev/prod режимы)
    runtime: Optional[Any] = getattr(getattr(request, "app", None), "state", None) and getattr(request.app.state, "runtime", None)
    cfg = getattr(runtime, "_config", None) if runtime is not None else None
    env = getattr(cfg, "env", "development") if cfg is not None else "development"
    csp_mode = getattr(cfg, "csp_mode", "relaxed") if cfg is not None else "relaxed"
    
    # X-Content-Type-Options: предотвращает MIME type sniffing
    # Браузер не будет пытаться угадать тип контента
    response.headers["X-Content-Type-Options"] = "nosniff"
    
    # X-Frame-Options: защита от clickjacking
    # Запрещает встраивание страницы в iframe
    response.headers["X-Frame-Options"] = "DENY"
    
    # X-XSS-Protection: включение XSS фильтра в старых браузерах
    # Современные браузеры используют CSP, но это для совместимости
    response.headers["X-XSS-Protection"] = "1; mode=block"
    
    # Дополнительные security headers (современные рекомендации)
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    # COEP может ломать некоторые интеграции; включаем только в strict CSP
    if csp_mode == "strict" or env == "production":
        response.headers["Cross-Origin-Embedder-Policy"] = "require-corp"

    # Strict-Transport-Security (HSTS): принудительное использование HTTPS
    # Включается только для HTTPS соединений
    # max-age=31536000 = 1 год
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    
    # Content-Security-Policy
    # В strict/prod запрещаем unsafe-inline/unsafe-eval.
    # В relaxed/dev оставляем совместимость (для Swagger/UI и dev tools).
    if csp_mode == "strict" or env == "production":
        csp_policy = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self'; "
            "img-src 'self' data: https:; "
            "font-src 'self' data:; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'none'; "
            "upgrade-insecure-requests"
        )
    else:
        csp_policy = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "font-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none';"
        )
    response.headers["Content-Security-Policy"] = csp_policy
    
    # Referrer-Policy: контролирует, какая информация отправляется в Referer header
    # strict-origin-when-cross-origin: отправляет полный URL для same-origin, только origin для cross-origin
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    
    # Permissions-Policy: контролирует доступ к браузерным API
    # Отключаем неиспользуемые API для безопасности
    permissions_policy = (
        "geolocation=(), "
        "microphone=(), "
        "camera=(), "
        "payment=(), "
        "usb=()"
    )
    response.headers["Permissions-Policy"] = permissions_policy
    
    return response
