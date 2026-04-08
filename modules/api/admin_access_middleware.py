"""
Admin Access Middleware — ограничение доступа к админ-панели.

Блокирует доступ к /admin/* endpoints если запрос не с localhost или не из приватной сети.
Это обеспечивает, что админ-панель доступна только при прямом подключении к ядру или через VPN.
При возврате 403 добавляем CORS-заголовки, иначе браузер скрывает ответ и фронт видит только CORS error.
"""

import ipaddress
from typing import Optional
from fastapi import Request, Response
import logging
logger = logging.getLogger(__name__)


def _add_cors_if_localhost(request: Request, response: Response) -> None:
    """Добавить CORS-заголовки к ответу для localhost origin."""
    origin = request.headers.get("origin")
    if not origin:
        return
    if origin.startswith("http://localhost") or origin.startswith("http://127.0.0.1"):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"


def is_private_ip(ip: str) -> bool:
    """
    Проверяет, является ли IP адрес приватным (localhost, private network, VPN).
    
    Args:
        ip: IP адрес в виде строки
    
    Returns:
        True если IP приватный, False если публичный
    """
    # Проверяем на localhost строку ПЕРЕД вызовом ipaddress.ip_address()
    # чтобы избежать ValueError при передаче "localhost"
    if ip == "127.0.0.1" or ip == "::1" or ip == "localhost":
        return True
    
    try:
        ip_obj = ipaddress.ip_address(ip)
        
        # Проверяем на приватные сети
        # 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16 (link-local)
        if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local:
            return True
        
        return False
    except ValueError:
        # Если IP невалиден, считаем его небезопасным
        return False


def get_client_ip(request: Request) -> Optional[str]:
    """
    Извлекает реальный IP адрес клиента из запроса.
    
    Учитывает заголовки X-Forwarded-For, X-Real-IP для работы за прокси.
    
    Args:
        request: FastAPI Request
    
    Returns:
        IP адрес клиента или None
    """
    # SECURITY: proxy headers можно подделать.
    # Доверяем X-Forwarded-For / X-Real-IP только если runtime конфиг явно разрешает это.
    trust_proxy_headers = False
    try:
        runtime = getattr(getattr(request, "app", None), "state", None) and getattr(request.app.state, "runtime", None)
        cfg = getattr(runtime, "_config", None) if runtime is not None else None
        trust_proxy_headers = bool(getattr(cfg, "trust_proxy_headers", False)) if cfg is not None else False
    except Exception:
        logger.debug("admin_access_middleware.get_client_ip: error (using fallback value)", exc_info=True)
        trust_proxy_headers = False

    if trust_proxy_headers:
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            ip = forwarded_for.split(",")[0].strip()
            if ip:
                return ip

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()
    
    # Используем IP из request.client
    if request.client:
        return request.client.host
    
    return None


async def admin_access_middleware(request: Request, call_next):
    """
    Middleware для ограничения доступа к админ-панели.
    
    Блокирует все запросы к /admin/* endpoints если они не с localhost или не из приватной сети.
    Это обеспечивает, что админ-панель доступна только:
    - При прямом подключении к ядру (localhost)
    - Через VPN (приватная сеть)
    - Не доступна из публичного интернета
    
    Args:
        request: FastAPI Request
        call_next: следующий middleware/handler
    
    Returns:
        Response (403 Forbidden если доступ запрещён)
    """
    path = str(request.url.path)
    
    # Проверяем только запросы к админ-панели
    if not path.startswith("/admin/"):
        # Не админ-запрос - пропускаем
        return await call_next(request)
    
    # Получаем IP адрес клиента
    client_ip = get_client_ip(request)
    
    if client_ip is None:
        # Не удалось определить IP - блокируем для безопасности
        r = Response(
            content='{"detail": "Access denied: unable to determine client IP address"}',
            status_code=403,
            media_type="application/json"
        )
        _add_cors_if_localhost(request, r)
        return r

    # Проверяем, является ли IP приватным
    if not is_private_ip(client_ip):
        # Публичный IP - блокируем доступ к админ-панели
        r = Response(
            content='{"detail": "Access denied: admin panel is only available from localhost or private network (VPN required)"}',
            status_code=403,
            media_type="application/json"
        )
        _add_cors_if_localhost(request, r)
        return r
    
    # Приватный IP - разрешаем доступ
    return await call_next(request)
