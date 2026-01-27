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
from typing import Callable


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
    
    # X-Content-Type-Options: предотвращает MIME type sniffing
    # Браузер не будет пытаться угадать тип контента
    response.headers["X-Content-Type-Options"] = "nosniff"
    
    # X-Frame-Options: защита от clickjacking
    # Запрещает встраивание страницы в iframe
    response.headers["X-Frame-Options"] = "DENY"
    
    # X-XSS-Protection: включение XSS фильтра в старых браузерах
    # Современные браузеры используют CSP, но это для совместимости
    response.headers["X-XSS-Protection"] = "1; mode=block"
    
    # Strict-Transport-Security (HSTS): принудительное использование HTTPS
    # Включается только для HTTPS соединений
    # max-age=31536000 = 1 год
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    
    # Content-Security-Policy: базовая политика безопасности контента
    # Разрешает только same-origin ресурсы и inline scripts/styles (для совместимости)
    # В production можно ужесточить
    csp_policy = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "  # unsafe-inline для разработки
        "style-src 'self' 'unsafe-inline'; "  # unsafe-inline для CSS
        "img-src 'self' data: https:; "
        "font-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none';"  # Эквивалент X-Frame-Options: DENY
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
