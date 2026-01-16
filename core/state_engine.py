"""
StateEngine - управление общим состоянием runtime.

Минимальный in-memory store для состояния runtime.
Не для бизнес-данных - только для координации плагинов.
"""

from typing import Any, Optional
import asyncio
import time


class StateEngine:
    """
    Хранилище общего состояния runtime.
    
    НЕ для бизнес-данных.
    Только для координации между плагинами.
    
    Примеры использования:
    - статус плагинов
    - флаги состояния системы
    - временные данные для координации
    """

    def __init__(self):
        # In-memory хранилище состояния
        self._state: dict[str, Any] = {}
        # TTL для ключей: key -> expiration timestamp
        self._ttl: dict[str, float] = {}
        # Lock для безопасности в async коде
        self._lock = asyncio.Lock()
        # Фоновая задача для очистки истёкших ключей
        self._cleanup_task: Optional[asyncio.Task] = None
        self._cleanup_running = False

    async def get(self, key: str) -> Optional[Any]:
        """
        Получить значение из состояния.
        
        Args:
            key: ключ
            
        Returns:
            Значение или None (если ключ истёк или не существует)
        """
        async with self._lock:
            # Проверяем TTL перед возвратом значения
            if key in self._ttl:
                if time.time() > self._ttl[key]:
                    # Ключ истёк - удаляем его
                    self._state.pop(key, None)
                    del self._ttl[key]
                    return None
            return self._state.get(key)

    async def set(self, key: str, value: Any) -> None:
        """
        Установить значение в состоянии.
        
        Args:
            key: ключ
            value: значение (может быть любым типом)
        """
        async with self._lock:
            self._state[key] = value
            # Удаляем TTL если был установлен (set без TTL = бессрочное хранение)
            self._ttl.pop(key, None)
    
    async def set_with_ttl(self, key: str, value: Any, ttl_seconds: float) -> None:
        """
        Установить значение в состоянии с TTL (time-to-live).
        
        Args:
            key: ключ
            value: значение (может быть любым типом)
            ttl_seconds: время жизни в секундах
        
        Пример:
            await state_engine.set_with_ttl("cache.key", {"data": "value"}, ttl_seconds=300)
            # Ключ автоматически удалится через 5 минут
        """
        async with self._lock:
            self._state[key] = value
            self._ttl[key] = time.time() + ttl_seconds
            # Запускаем фоновую задачу очистки, если ещё не запущена
            if not self._cleanup_running:
                self._start_cleanup_task()

    async def delete(self, key: str) -> bool:
        """
        Удалить значение из состояния.
        
        Args:
            key: ключ
            
        Returns:
            True если значение было удалено
        """
        async with self._lock:
            if key in self._state:
                del self._state[key]
                self._ttl.pop(key, None)
                return True
            return False

    async def exists(self, key: str) -> bool:
        """
        Проверить существование ключа.
        
        Args:
            key: ключ
            
        Returns:
            True если ключ существует
        """
        async with self._lock:
            return key in self._state

    async def keys(self) -> list[str]:
        """
        Получить список всех ключей.
        
        Returns:
            Список ключей
        """
        async with self._lock:
            return list(self._state.keys())

    async def clear(self) -> None:
        """Очистить всё состояние."""
        async with self._lock:
            self._state.clear()
            self._ttl.clear()
            # Останавливаем фоновую задачу очистки
            if self._cleanup_task and not self._cleanup_task.done():
                self._cleanup_task.cancel()
                self._cleanup_running = False
    
    def _start_cleanup_task(self) -> None:
        """Запустить фоновую задачу для очистки истёкших ключей."""
        if self._cleanup_running:
            return
        
        self._cleanup_running = True
        
        async def _cleanup_expired() -> None:
            """Фоновая задача для очистки истёкших ключей."""
            while self._cleanup_running:
                try:
                    await asyncio.sleep(60)  # Проверяем каждую минуту
                    now = time.time()
                    async with self._lock:
                        expired = [k for k, exp in self._ttl.items() if exp < now]
                        for k in expired:
                            self._state.pop(k, None)
                            del self._ttl[k]
                        # Если больше нет ключей с TTL, останавливаем задачу
                        if not self._ttl:
                            self._cleanup_running = False
                            break
                except asyncio.CancelledError:
                    self._cleanup_running = False
                    break
                except Exception:
                    # Игнорируем ошибки в фоновой задаче
                    pass
        
        self._cleanup_task = asyncio.create_task(_cleanup_expired())

    async def update(self, updates: dict[str, Any]) -> None:
        """
        Обновить несколько значений одновременно.
        
        Args:
            updates: словарь с обновлениями
        """
        async with self._lock:
            self._state.update(updates)
