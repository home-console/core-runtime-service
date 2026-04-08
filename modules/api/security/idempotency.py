"""
Idempotency support для защиты от race conditions.

Гарантирует, что одинаковые запросы (с одинаковым Idempotency-Key)
выполняются только один раз в течение заданного TTL.
"""

from typing import Optional, Dict, Any, Callable
from fastapi import Request, Response
from starlette.responses import StreamingResponse
import json
import time
import hashlib
import logging
logger = logging.getLogger(__name__)


class IdempotencyStore:
    """In-memory хранилище для idempotency keys (для dev/testing)."""
    
    def __init__(self, ttl_seconds: int = 3600):
        """
        Args:
            ttl_seconds: TTL для сохранения результатов (по умолчанию 1 час)
        """
        self.ttl = ttl_seconds
        self._store: Dict[str, Dict[str, Any]] = {}
    
    async def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Получить сохранённый результат по ключу."""
        if key in self._store:
            entry = self._store[key]
            # Проверяем, не истек ли TTL
            if time.time() - entry.get("timestamp", 0) < self.ttl:
                # Возвращаем оригинальное сохранённое значение (tests expect stored value)
                return entry.get("value")
            else:
                # Удаляем истекший ключ
                del self._store[key]
        return None
    
    async def set(self, key: str, response_data: Dict[str, Any]) -> None:
        """Сохранить результат запроса."""
        # Store the original response_data under "value" and metadata separately
        self._store[key] = {
            "value": response_data,
            "timestamp": time.time()
        }
    
    async def cleanup_expired(self) -> None:
        """Удалить все истекшие ключи."""
        current_time = time.time()
        expired_keys = [
            key for key, entry in self._store.items()
            if current_time - entry.get("timestamp", 0) >= self.ttl
        ]
        for key in expired_keys:
            del self._store[key]


# Global idempotency store (for single-process deployment)
# В production это должно быть Redis или аналогичное
_idempotency_store = IdempotencyStore(ttl_seconds=3600)


def get_idempotency_key(request: Request) -> Optional[str]:
    """
    Извлекает Idempotency-Key из заголовков запроса.
    
    Args:
        request: FastAPI Request
    
    Returns:
        Idempotency-Key или None если не указан
    
    Примечание:
        RFC 7231: Idempotency-Key = token
        Должен быть уникален для каждого logically distinct запроса
    """
    key = request.headers.get("Idempotency-Key")
    if key:
        # Валидируем длину (не должен быть слишком длинным)
        if len(key) > 256:
            return None
        return key.strip()
    return None


async def idempotency_middleware(request: Request, call_next: Callable) -> Response:
    """
    Middleware для обработки Idempotency-Key.
    
    Для state-changing операций (POST, PUT, DELETE):
    1. Проверяет наличие Idempotency-Key
    2. Если ключ есть и мы уже видели такой запрос — возвращаем сохранённый результат
    3. Если ключ новый — выполняем запрос и сохраняем результат
    
    Args:
        request: FastAPI Request
        call_next: следующий middleware/handler
    
    Returns:
        Response (либо сохранённый, либо новый)
    """
    # Проверяем только state-changing методы
    if request.method not in ("POST", "PUT", "DELETE", "PATCH"):
        return await call_next(request)
    
    idempotency_key = get_idempotency_key(request)
    
    if not idempotency_key:
        # Нет Idempotency-Key — просто выполняем запрос
        return await call_next(request)
    
    # Fingerprint the request to prevent key reuse across different operations.
    # We bind the stored result to method+path+body hash.
    try:
        body_bytes = await request.body()
    except Exception:
        logger.debug("idempotency.idempotency_middleware: error (using fallback value)", exc_info=True)
        body_bytes = b""
    body_hash = hashlib.sha256(body_bytes).hexdigest()
    fingerprint = f"{request.method}:{request.url.path}:{body_hash}"
    storage_key = hashlib.sha256(f"{idempotency_key}:{fingerprint}".encode("utf-8")).hexdigest()

    # Проверяем, есть ли уже сохранённый результат
    cached = await _idempotency_store.get(storage_key)
    if cached:
        # Возвращаем сохранённый результат (status_code и body) с пометкой replay
        response = Response(
            content=cached.get("body", b"") if isinstance(cached.get("body"), (bytes, bytearray)) else json.dumps(cached.get("response", {})),
            status_code=cached.get("status_code", 200),
            media_type=cached.get("media_type", "application/json"),
            headers=cached.get("headers") or None,
        )
        # Добавляем заголовок, который показывает, что это replayed response
        response.headers["Idempotency-Replay"] = "true"
        return response
    
    # Выполняем настоящий запрос
    response = await call_next(request)

    # Do not attempt to cache streaming responses (would consume the stream).
    if isinstance(response, StreamingResponse):
        return response
    
    # Сохраняем результат (но только для успешных ответов)
    if response.status_code < 400:
        try:
            # Prefer response.body when available (avoids consuming iterators).
            body = getattr(response, "body", None)
            if body is None:
                body = b""
                async for chunk in response.body_iterator:
                    body += chunk
            
            headers = dict(response.headers)
            # Avoid caching hop-by-hop / non-deterministic headers
            headers.pop("content-length", None)
            headers.pop("date", None)
            headers.pop("server", None)

            response_data: Dict[str, Any] = {
                "status_code": response.status_code,
                "media_type": response.media_type,
                "headers": headers,
                "body": body,
            }
            
            await _idempotency_store.set(storage_key, response_data)
            
            # Возвращаем новый Response с тем же content
            return Response(
                content=body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type
            )
        except Exception as e:
            # Если ошибка при сохранении — просто возвращаем оригинальный ответ
            logger.warning("idempotency.idempotency_middleware: failed: %s", e, exc_info=True)
            return response
    
    return response


async def periodic_cleanup() -> None:
    """
    Периодическая очистка истекших idempotency ключей.
    
    Должна вызваться в фоновой задаче (например, каждые 5 минут).
    """
    await _idempotency_store.cleanup_expired()
