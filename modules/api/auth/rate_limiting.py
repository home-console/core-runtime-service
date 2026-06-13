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
import logging
logger = logging.getLogger(__name__)


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
    Uses storage transaction to prevent TOCTOU race conditions.
    
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
    services = getattr(runtime, "service_registry", None)

    try:
        if not identifier:
            return True
        
        if not isinstance(identifier, str):
            identifier = str(identifier)
        
        if not isinstance(limit_type, str):
            limit_type = str(limit_type)
        
        rate_key = hashlib.sha256(f"{limit_type}:{identifier}".encode()).hexdigest()

        async def _check_and_increment(storage: Any) -> bool:
            rate_data = await storage.get(AUTH_RATE_LIMITS_NAMESPACE, rate_key)
            current_time = time.time()
            
            if rate_data is None or not isinstance(rate_data, dict):
                rate_data = {
                    "count": 1,
                    "window_start": current_time,
                    "last_attempt": current_time
                }
                await storage.set(AUTH_RATE_LIMITS_NAMESPACE, rate_key, rate_data)
                return True
            
            window_start = rate_data.get("window_start", current_time)
            count = rate_data.get("count", 0)
            
            if current_time - window_start >= window_seconds:
                rate_data = {
                    "count": 1,
                    "window_start": current_time,
                    "last_attempt": current_time
                }
                await storage.set(AUTH_RATE_LIMITS_NAMESPACE, rate_key, rate_data)
                return True
            
            if count >= limit:
                return False
            
            rate_data["count"] = count + 1
            rate_data["last_attempt"] = current_time
            await storage.set(AUTH_RATE_LIMITS_NAMESPACE, rate_key, rate_data)
            return True

        # Wrap in transaction to prevent TOCTOU race
        storage = runtime.storage
        try:
            if hasattr(storage, 'transaction'):
                async with storage.transaction():
                    return await _check_and_increment(storage)
        except (TypeError, AttributeError):
            # Mock or storage without proper transaction support — fall through
            pass
        return await _check_and_increment(storage)
    
    except Exception as e:
        try:
            if services is not None:
                await services.call(
                    "logger.log",
                    level="error",
                    message=f"Rate limit check error: {e}",
                    module="api"
                )
        except Exception:
            logger.warning("Unhandled exception", exc_info=True)
        return True  # Fail-open
