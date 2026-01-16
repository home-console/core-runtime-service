"""
Rate limiting — защита от brute force атак и злоупотреблений.
"""

from typing import Any, Optional
import time
import hashlib

from .constants import (
    AUTH_RATE_LIMITS_NAMESPACE,
    RATE_LIMIT_AUTH_ATTEMPTS,
    RATE_LIMIT_AUTH_WINDOW,
    RATE_LIMIT_API_REQUESTS,
    RATE_LIMIT_API_WINDOW
)


async def rate_limit_check(
    runtime: Any,
    identifier: str,
    limit_type: str = "auth",
    limit: Optional[int] = None,
    window_seconds: Optional[int] = None
) -> bool:
    """
    Проверяет rate limit для идентификатора.
    
    Защита от brute force атак.
    
    Args:
        runtime: экземпляр CoreRuntime
        identifier: API key, session_id или IP address
        limit_type: "auth" (для auth попыток) или "api" (для API запросов)
        limit: максимальное количество попыток (по умолчанию из констант)
        window_seconds: окно времени в секундах (по умолчанию из констант)
    
    Returns:
        True если лимит не превышен, False если превышен
    """
    if limit is None:
        limit = RATE_LIMIT_AUTH_ATTEMPTS if limit_type == "auth" else RATE_LIMIT_API_REQUESTS
    
    if window_seconds is None:
        window_seconds = RATE_LIMIT_AUTH_WINDOW if limit_type == "auth" else RATE_LIMIT_API_WINDOW
    
    try:
        # Проверяем, что identifier не None и является строкой
        if not identifier:
            return True  # Fail-open: если нет идентификатора, разрешаем запрос
        
        # Нормализуем identifier в строку
        if not isinstance(identifier, str):
            identifier = str(identifier)
        
        # Проверяем, что limit_type тоже строка
        if not isinstance(limit_type, str):
            limit_type = str(limit_type)
        
        # Создаём ключ для rate limit (hash для безопасности)
        rate_key = hashlib.sha256(f"{limit_type}:{identifier}".encode()).hexdigest()
        
        # Получаем текущий счётчик
        rate_data = await runtime.storage.get(AUTH_RATE_LIMITS_NAMESPACE, rate_key)
        
        current_time = time.time()
        
        if rate_data is None or not isinstance(rate_data, dict):
            # Первая попытка - создаём счётчик
            rate_data = {
                "count": 1,
                "window_start": current_time,
                "last_attempt": current_time
            }
            await runtime.storage.set(AUTH_RATE_LIMITS_NAMESPACE, rate_key, rate_data)
            return True
        
        window_start = rate_data.get("window_start", current_time)
        count = rate_data.get("count", 0)
        
        # Проверяем, не истёк ли window
        if current_time - window_start >= window_seconds:
            # Окно истекло - сбрасываем счётчик
            rate_data = {
                "count": 1,
                "window_start": current_time,
                "last_attempt": current_time
            }
            await runtime.storage.set(AUTH_RATE_LIMITS_NAMESPACE, rate_key, rate_data)
            return True
        
        # Проверяем лимит
        if count >= limit:
            return False
        
        # Увеличиваем счётчик
        rate_data["count"] = count + 1
        rate_data["last_attempt"] = current_time
        await runtime.storage.set(AUTH_RATE_LIMITS_NAMESPACE, rate_key, rate_data)
        return True
    
    except Exception as e:
        # При ошибке разрешаем запрос (fail-open для доступности)
        try:
            await runtime.service_registry.call(
                "logger.log",
                level="error",
                message=f"Rate limit check error: {e}",
                module="api"
            )
        except Exception:
            pass
        return True  # Fail-open
