"""
StateEngine - управление общим состоянием runtime.

Минимальный in-memory store для состояния runtime.
Не для бизнес-данных - только для координации плагинов.
"""

from typing import Any, Optional
import asyncio


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
        # Lock для безопасности в async коде
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        """
        Получить значение из состояния.
        
        Args:
            key: ключ
            
        Returns:
            Значение или None
        """
        async with self._lock:
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

    async def update(self, updates: dict[str, Any]) -> None:
        """
        Обновить несколько значений одновременно.
        
        Args:
            updates: словарь с обновлениями
        """
        async with self._lock:
            self._state.update(updates)
