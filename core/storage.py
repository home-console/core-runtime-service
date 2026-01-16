"""
Storage API - единый интерфейс для работы с хранилищем.

Плагины работают ТОЛЬКО через этот API.
Никакого прямого доступа к БД.
"""

from typing import Any, Optional, Callable, Awaitable
from contextlib import asynccontextmanager

from adapters.storage_adapter import StorageAdapter


class Storage:
    """
    Storage API для плагинов.
    
    Простой интерфейс: namespace + key + JSON value.
    Без моделей, без ORM, без схемы.
    """

    def __init__(self, adapter: StorageAdapter):
        """ Инициализация Storage. adapter: адаптер для работы с хранилищем """
        self._adapter = adapter

    async def get(self, namespace: str, key: str) -> Optional[dict[str, Any]]:
        """
        Получить значение.
        
        Args:
            namespace: пространство имён (непустая строка)
            key: ключ записи (непустая строка)
            
        Returns:
            Значение или None если не найдено
            
        Raises:
            ValueError: если namespace или key пустые или не строки
            
        Пример:
            value = await storage.get("devices", "lamp_1")
        """
        if not isinstance(namespace, str) or not namespace:
            raise ValueError(
                f"namespace must be non-empty string, got {type(namespace).__name__}: {namespace!r}"
            )
        if not isinstance(key, str) or not key:
            raise ValueError(
                f"key must be non-empty string, got {type(key).__name__}: {key!r}"
            )
        return await self._adapter.get(namespace, key)

    async def set(self, namespace: str, key: str, value: dict[str, Any]) -> None:
        """
        Сохранить значение.
        
        Args:
            namespace: пространство имён (непустая строка)
            key: ключ записи (непустая строка)
            value: данные для сохранения (должен быть dict)
            
        Raises:
            TypeError: если value не является dict
            ValueError: если namespace или key пустые или не строки
            
        Пример:
            await storage.set("devices", "lamp_1", {"state": "on", "value": 100})
        """
        # Валидация типов
        if not isinstance(value, dict):
            raise TypeError(
                f"value must be dict, got {type(value).__name__}: {value}"
            )
        if not isinstance(namespace, str) or not namespace:
            raise ValueError(
                f"namespace must be non-empty string, got {type(namespace).__name__}: {namespace!r}"
            )
        if not isinstance(key, str) or not key:
            raise ValueError(
                f"key must be non-empty string, got {type(key).__name__}: {key!r}"
            )
        
        await self._adapter.set(namespace, key, value)

    async def delete(self, namespace: str, key: str) -> bool:
        """
        Удалить значение.
        
        Args:
            namespace: пространство имён (непустая строка)
            key: ключ записи (непустая строка)
            
        Returns:
            True если запись была удалена, False если не существовала
            
        Raises:
            ValueError: если namespace или key пустые или не строки
        """
        if not isinstance(namespace, str) or not namespace:
            raise ValueError(
                f"namespace must be non-empty string, got {type(namespace).__name__}: {namespace!r}"
            )
        if not isinstance(key, str) or not key:
            raise ValueError(
                f"key must be non-empty string, got {type(key).__name__}: {key!r}"
            )
        return await self._adapter.delete(namespace, key)

    async def list_keys(self, namespace: str) -> list[str]:
        """
        Получить список всех ключей в namespace.
        
        Args:
            namespace: пространство имён (непустая строка)
            
        Returns:
            Список ключей
            
        Raises:
            ValueError: если namespace пустой или не строка
            
        Пример:
            keys = await storage.list_keys("devices")
        """
        if not isinstance(namespace, str) or not namespace:
            raise ValueError(
                f"namespace must be non-empty string, got {type(namespace).__name__}: {namespace!r}"
            )
        return await self._adapter.list_keys(namespace)

    async def clear_namespace(self, namespace: str) -> None:
        """Очистить все записи в namespace."""
        await self._adapter.clear_namespace(namespace)

    async def close(self) -> None:
        """Закрыть соединение."""
        await self._adapter.close()
    
    @asynccontextmanager
    async def transaction(self):
        """
        Контекстный менеджер для транзакций.
        
        Использование:
            async with storage.transaction():
                await storage.set("ns", "key1", {"value": 1})
                await storage.set("ns", "key2", {"value": 2})
                # Все операции выполняются в одной транзакции
                # При выходе из блока транзакция коммитится
                # При исключении - откатывается
        
        Yields:
            None (контекстный менеджер для управления транзакцией)
        """
        async with self._adapter.transaction():
            yield
    
    async def transaction_callback(self, callback: Callable[["Storage"], Awaitable[Any]]) -> Any:
        """
        Выполнить callback в транзакции.
        
        Args:
            callback: асинхронная функция, принимающая Storage и возвращающая результат
        
        Returns:
            Результат выполнения callback
        
        Пример:
            result = await storage.transaction_callback(async def(storage):
                await storage.set("ns", "key1", {"value": 1})
                await storage.set("ns", "key2", {"value": 2})
                return "done"
            )
        """
        async with self.transaction():
            return await callback(self)
    
    async def batch_set(self, namespace: str, items: dict[str, dict[str, Any]]) -> None:
        """
        Массовая запись значений в namespace.
        
        Оптимизированная операция для записи множества значений за один раз.
        Может быть быстрее множественных вызовов set() за счёт использования
        batch операций адаптера.
        
        Args:
            namespace: пространство имён
            items: словарь {key: value}, где value - это dict с данными
        
        Raises:
            ValueError: если namespace пустой или не строка
            TypeError: если items не является dict или содержит не-dict значения
        
        Пример:
            await storage.batch_set("devices", {
                "device1": {"name": "Lamp 1", "state": "on"},
                "device2": {"name": "Lamp 2", "state": "off"}
            })
        """
        if not isinstance(namespace, str) or not namespace:
            raise ValueError(
                f"namespace must be non-empty string, got {type(namespace).__name__}: {namespace!r}"
            )
        if not isinstance(items, dict):
            raise TypeError(f"items must be dict, got {type(items).__name__}")
        
        # Валидация значений
        for key, value in items.items():
            if not isinstance(value, dict):
                raise TypeError(
                    f"items[{key!r}] must be dict, got {type(value).__name__}"
                )
        
        await self._adapter.batch_set(namespace, items)