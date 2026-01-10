"""
Storage API - единый интерфейс для работы с хранилищем.

Плагины работают ТОЛЬКО через этот API.
Никакого прямого доступа к БД.
"""

from typing import Any, Optional

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
