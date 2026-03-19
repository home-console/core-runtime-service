"""
Абстрактный интерфейс для storage адаптеров.

Storage работает по принципу namespace + key + JSON value.
Никаких моделей, никакой ORM, никакой схемы.
"""

from abc import ABC, abstractmethod
from typing import Any, Optional, AsyncIterator
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
    async def list_namespaces(self) -> list[str]:
        """
        Получить список всех namespace, присутствующих в хранилище.

        Returns:
            Отсортированный список уникальных namespace.

        NOTE: это API используется только для introspection/inspector
        (админский read‑only просмотр), не для бизнес‑логики плагинов.
        """
        pass

    async def iter_namespaces(self) -> AsyncIterator[str]:
        """
        Итерировать по всем namespace в хранилище (async iterator).

        Default implementation delegates to `list_namespaces()` and yields
        each namespace. Individual adapters may override for streaming.
        """
        namespaces = await self.list_namespaces()
        for ns in namespaces:
            yield ns

    @abstractmethod
    async def initialize_schema(self) -> None:
        """
        Инициализация схемы хранилища (создать таблицы и т.п.).
        Вызывается при startup (await adapter.initialize_schema()).
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
    
    @asynccontextmanager
    @abstractmethod
    async def transaction(self) -> AsyncIterator[None]:
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
            None (контекстный менеджер для управления транзакцией)
        """
        yield  # pragma: no cover
    
    @abstractmethod
    async def batch_set(self, namespace: str, items: dict[str, dict[str, Any]]) -> None:
        """
        Массовая запись значений в namespace.
        
        Args:
            namespace: пространство имён
            items: словарь {key: value}, где value - это dict с данными
        
        Пример:
            await adapter.batch_set("devices", {
                "device1": {"name": "Lamp 1", "state": "on"},
                "device2": {"name": "Lamp 2", "state": "off"}
            })
        """
        pass
    
    @abstractmethod
    async def iter_namespace(self, namespace: str, batch_size: int = 100) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """
        Итерировать по всем ключам в namespace батчами (для efficient streaming больших namespace).
        
        Args:
            namespace: пространство имён
            batch_size: размер батча для fetch (default 100)
            
        Yields:
            (key, value) кортежи
            
        Пример:
            async for key, value in adapter.iter_namespace("devices"):
                process(key, value)
        
        This is efficient for large namespaces and avoids loading everything into memory.
        """
        return
        yield  # pragma: no cover