"""
DedupLayer — персистентный слой dedup для операций и событий.

Контракт ключей, TTL и политика at-least-once: ``dedup_contract`` и
``docs/adr/001-dedup-at-least-once-contract.md``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

from core.adapters.storage_errors import STORAGE_BOUNDARY_ERRORS
from core.exception_groups import BEST_EFFORT_BACKGROUND_ERRORS
from core.operations.dedup_contract import (
    DEFAULT_DEDUP_TTL_SECONDS,
    DEDUP_STORAGE_NAMESPACE,
    storage_key_for_event,
    storage_key_for_operation,
)

logger = logging.getLogger(__name__)


class DedupLayer:
    """
    Централизованный слой для deduplication операций и событий.
    
    Использует storage для персистентности + in-memory кэш для производительности.
    """

    def __init__(self, storage: Any, ttl_seconds: int = DEFAULT_DEDUP_TTL_SECONDS):
        """
        Инициализация dedup layer.
        
        Args:
            storage: Storage port для персистентности
            ttl_seconds: Время жизни записей в секундах (по умолчанию 1 час)
        """
        self._storage = storage
        self._ttl_seconds = ttl_seconds
        self._memory_cache: dict[str, float] = {}  # key -> expiry_timestamp
        self._lock = asyncio.Lock()

    async def is_operation_processed(self, operation_id: str) -> bool:
        """
        Проверить была ли операция уже обработана.
        
        Args:
            operation_id: ID операции
            
        Returns:
            True если операция уже обработана, False иначе
        """
        key = storage_key_for_operation(operation_id)
        return await self._is_key_present(key)

    async def mark_operation_processed(self, operation_id: str) -> bool:
        """
        Отметить операцию как обработанную.
        
        Args:
            operation_id: ID операции
            
        Returns:
            True если операция успешно отмечена, False если уже была обработана
        """
        key = storage_key_for_operation(operation_id)
        return await self._set_key_if_absent(key)

    async def is_event_processed(self, event_id: str) -> bool:
        """
        Проверить было ли событие уже обработано.
        
        Args:
            event_id: ID события
            
        Returns:
            True если событие уже обработано, False иначе
        """
        key = storage_key_for_event(event_id)
        return await self._is_key_present(key)

    async def mark_event_processed(self, event_id: str) -> bool:
        """
        Отметить событие как обработанное.
        
        Args:
            event_id: ID события
            
        Returns:
            True если событие успешно отмечено, False если уже было обработано
        """
        key = storage_key_for_event(event_id)
        return await self._set_key_if_absent(key)

    async def _is_key_present(self, key: str) -> bool:
        """
        Проверить наличие ключа в кэше или storage.
        
        Args:
            key: Ключ для проверки
            
        Returns:
            True если ключ присутствует и не истёк, False иначе
        """
        # Сначала проверяем in-memory кэш
        now = time.time()
        if key in self._memory_cache:
            expiry = self._memory_cache[key]
            if expiry > now:
                return True
            else:
                # Истёк, удаляем из кэша
                del self._memory_cache[key]

        # Проверяем storage
        try:
            value = await self._storage.get(DEDUP_STORAGE_NAMESPACE, key)
            if value is not None:
                expiry = float(value)
                if expiry > now:
                    return True
                else:
                    # Истёк, удаляем из storage
                    await self._storage.delete(DEDUP_STORAGE_NAMESPACE, key)
        except STORAGE_BOUNDARY_ERRORS:
            logger.debug(
                "dedup._is_key_present: storage boundary (cache-only fallback)",
                exc_info=True,
            )
        except BEST_EFFORT_BACKGROUND_ERRORS:
            logger.warning(
                "dedup._is_key_present: unexpected error (cache-only fallback)",
                exc_info=True,
            )

        return False

    async def _set_key_if_absent(self, key: str) -> bool:
        """
        Установить ключ только если он ещё не существует (атомарно).
        
        Args:
            key: Ключ для установки
            
        Returns:
            True если ключ успешно установлен, False если уже существовал
        """
        async with self._lock:
            # Проверяем не существует ли уже ключ
            if await self._is_key_present(key):
                return False

            # Устанавливаем в кэш и storage
            now = time.time()
            expiry = now + self._ttl_seconds
            self._memory_cache[key] = expiry

            try:
                await self._storage.set(DEDUP_STORAGE_NAMESPACE, key, str(expiry))
            except STORAGE_BOUNDARY_ERRORS:
                logger.debug(
                    "dedup._set_key_if_absent: storage boundary (cache-only)",
                    exc_info=True,
                )
            except BEST_EFFORT_BACKGROUND_ERRORS:
                logger.warning(
                    "dedup._set_key_if_absent: unexpected error (cache-only)",
                    exc_info=True,
                )

            return True

    async def cleanup_expired(self) -> int:
        """
        Очистить истёкшие записи из кэша.
        
        Returns:
            Количество очищенных записей
        """
        now = time.time()
        expired_keys = [
            key for key, expiry in self._memory_cache.items()
            if expiry <= now
        ]
        for key in expired_keys:
            del self._memory_cache[key]
        return len(expired_keys)

    def get_cache_size(self) -> int:
        """
        Получить размер in-memory кэша.
        
        Returns:
            Количество записей в кэше
        """
        return len(self._memory_cache)
