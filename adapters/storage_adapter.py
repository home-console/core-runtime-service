"""
Абстрактный интерфейс для storage адаптеров.

Storage работает по принципу namespace + key + JSON value.
Никаких моделей, никакой ORM, никакой схемы.
"""

from abc import ABC, abstractmethod
from typing import Any, Optional, AsyncContextManager
from contextlib import asynccontextmanager


class StorageAdapter(ABC):
    """Абстрактный адаптер для хранения данных."""

    @abstractmethod
    async def get(self, namespace: str, key: str) -> Optional[dict[str, Any]]:
        """
        Получить значение по ключу из namespace.
        
        Args:
            namespace: пространство имён (например, "devices")
            key: ключ записи (например, "lamp_kitchen")
            
        Returns:
            JSON-данные или None, если не найдено
        """
        pass

    @abstractmethod
    async def set(self, namespace: str, key: str, value: dict[str, Any]) -> None:
        """
        Сохранить значение по ключу в namespace.
        
        Args:
            namespace: пространство имён
            key: ключ записи
            value: JSON-данные для сохранения
        """
        pass

    @abstractmethod
    async def delete(self, namespace: str, key: str) -> bool:
        """
        Удалить значение по ключу из namespace.
        
        Args:
            namespace: пространство имён
            key: ключ записи
            
        Returns:
            True если запись была удалена, False если не существовала
        """
        pass

    @abstractmethod
    async def list_keys(self, namespace: str) -> list[str]:
        """
        Получить список всех ключей в namespace.
        
        Args:
            namespace: пространство имён
            
        Returns:
            Список ключей
        """
        pass

    @abstractmethod
    async def clear_namespace(self, namespace: str) -> None:
        """
        Очистить все записи в namespace.
        
        Args:
            namespace: пространство имён
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """Закрыть соединение с хранилищем."""
        pass
    
    @abstractmethod
    @asynccontextmanager
    async def transaction(self) -> AsyncContextManager[Any]:
        """
        Контекстный менеджер для транзакций.
        
        Использование:
            async with adapter.transaction():
                await adapter.set("ns", "key1", {"value": 1})
                await adapter.set("ns", "key2", {"value": 2})
                # Все операции выполняются в одной транзакции
                # При выходе из блока транзакция коммитится
                # При исключении - откатывается
        
        Yields:
            Объект транзакции (зависит от реализации адаптера)
        """
        pass