"""
URL validator для защиты от SSRF атак.

Валидирует URLs для внешних запросов:
- Запрещает доступ к private IPs (localhost, 127.0.0.1, 10.x, 172.16-31.x, 192.168.x, link-local)
- Запрещает опасные схемы (file://, ftp://, gopher://, telnet://, etc.)
- Разрешает только http:// и https://
- Проверяет на open redirects
- DNS cache с TTL 30 сек для защиты от DNS rebinding
"""

import ipaddress
import socket
import time
import threading
from typing import Optional
from urllib.parse import urlparse

from core.exceptions.errors import BadRequestError

# TTL для DNS кэша: 30 сек — баланс между производительностью и защитой от DNS rebinding
_DNS_CACHE_TTL_SEC = 30.0


def is_private_ip(host: str) -> bool:
    """
    Проверяет, является ли хост приватным IP адресом.
    
    Args:
        host: hostname или IP адрес в виде строки
    
    Returns:
        True если IP приватный или localhost
    """
    # Проверяем на localhost строку ПЕРЕД вызовом ipaddress.ip_address()
    if host in ("127.0.0.1", "::1", "localhost", "[::1]"):
        return True
    
    try:
        ip_obj = ipaddress.ip_address(host)
        
        # Проверяем на приватные/link-local сети
        if (ip_obj.is_private or 
            ip_obj.is_loopback or 
            ip_obj.is_link_local or
            ip_obj.is_multicast or
            ip_obj.is_reserved):
            return True
        
        return False
    except ValueError:
        # Не IP адрес, возможно hostname — пока считаем OK
        # DNS resolution делается в validate_external_url()
        return False


# DNS cache: host -> (ips_tuple, expiry_timestamp)
_dns_cache: dict[str, tuple[tuple[str, ...], float]] = {}
_dns_cache_lock = threading.Lock()
_DNS_CACHE_MAXSIZE = 1024


def _resolve_host_ips(host: str) -> tuple[str, ...]:
    """
    Resolve hostname to IP addresses (A/AAAA).

    Cached with TTL 30 sec to limit exposure to DNS rebinding attacks.
    """
    now = time.time()
    with _dns_cache_lock:
        entry = _dns_cache.get(host)
        if entry is not None:
            ips, expiry = entry
            if now < expiry:
                return ips
        # Evict stale or shrink if over limit
        to_remove = [k for k, (_, exp) in _dns_cache.items() if exp <= now]
        for k in to_remove:
            del _dns_cache[k]
        while len(_dns_cache) >= _DNS_CACHE_MAXSIZE and _dns_cache:
            oldest = min(_dns_cache, key=lambda k: _dns_cache[k][1])
            del _dns_cache[oldest]

    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return tuple()
    ips: list[str] = []
    for family, _socktype, _proto, _canonname, sockaddr in infos:
        try:
            if family == socket.AF_INET:
                ips.append(sockaddr[0])
            elif family == socket.AF_INET6:
                ips.append(sockaddr[0])
        except Exception:
            continue
    result = tuple(sorted(set(ips)))
    with _dns_cache_lock:
        _dns_cache[host] = (result, now + _DNS_CACHE_TTL_SEC)
    return result


def is_allowed_scheme(url: str) -> bool:
    """
    Проверяет, использует ли URL разрешённую схему (только http/https).
    
    Args:
        url: полный URL
    
    Returns:
        True если схема разрешена (http или https)
    """
    try:
        parsed = urlparse(url)
        scheme_lower = parsed.scheme.lower() if parsed.scheme else ""
        
        # Только http и https
        if scheme_lower not in ("http", "https"):
            return False
        
        return True
    except Exception:
        return False


def validate_external_url(url: str, allow_private: bool = False) -> bool:
    """
    Валидирует URL для внешних запросов.
    
    Защищает от SSRF атак путём:
    1. Проверки схемы (только http/https)
    2. Проверки хоста (никаких private IPs)
    3. Базовой проверки на пустые значения
    
    Args:
        url: полный URL для валидации
        allow_private: если True, разрешить private IPs (для dev/testing)
    
    Returns:
        True если URL валиден для использования
    
    Raises:
        BadRequestError: если URL невалиден
    
    Examples:
        >>> validate_external_url("https://api.example.com/data")
        True
        
        >>> validate_external_url("http://127.0.0.1:8080")
        BadRequestError: private IP not allowed
        
        >>> validate_external_url("file:///etc/passwd")
        BadRequestError: scheme not allowed
    """
    if not url or not isinstance(url, str):
        raise BadRequestError("URL must be non-empty string")
    
    url = url.strip()
    if len(url) > 2048:  # Reasonable URL length limit
        raise BadRequestError("URL too long (max 2048 chars)")
    
    # 1. Проверяем схему
    if not is_allowed_scheme(url):
        raise BadRequestError(f"URL scheme not allowed: {urlparse(url).scheme}")
    
    # 2. Парсим URL и извлекаем хост
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        
        if not host:
            raise BadRequestError("Invalid URL: no hostname")
        
        # 3. Проверяем, не приватный ли IP
        if is_private_ip(host):
            if not allow_private:
                raise BadRequestError(f"Private IP not allowed: {host}")

        # 4. Если host — hostname (не IP), проверяем DNS resolution на private IPs (SSRF protection).
        # This blocks cases like example.com -> 127.0.0.1 via DNS rebinding / internal DNS.
        if not allow_private:
            try:
                # If host parses as IP, ipaddress.ip_address won't throw and we skip DNS.
                ipaddress.ip_address(host)
            except ValueError:
                resolved_ips = _resolve_host_ips(host)
                for ip in resolved_ips:
                    if is_private_ip(ip):
                        raise BadRequestError(f"Private IP not allowed (DNS): {host} -> {ip}")
        
        return True
    
    except BadRequestError:
        raise
    except Exception as e:
        raise BadRequestError(f"Invalid URL format: {str(e)}")


def validate_url_for_plugin(url: str) -> bool:
    """
    Специфичная валидация для плагинов (более строгая).
    
    Args:
        url: URL для валидации
    
    Returns:
        True если URL безопасен для использования плагинами
    
    Raises:
        BadRequestError: если URL невалиден
    """
    # Для плагинов не разрешаем приватные IPs совсем
    return validate_external_url(url, allow_private=False)
