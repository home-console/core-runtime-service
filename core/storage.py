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
        """
        Инициализация Storage.
        
        Args:
            adapter: адаптер для работы с хранилищем
        """
        self._adapter = adapter

    async def get(self, namespace: str, key: str) -> Optional[dict[str, Any]]:
        """
        Получить значение.
        
        Пример:
            value = await storage.get("devices", "lamp_kitchen")
        """
        return await self._adapter.get(namespace, key)

    async def set(self, namespace: str, key: str, value: dict[str, Any]) -> None:
        """
        Сохранить значение.
        
        Пример:
            await storage.set("devices", "lamp_kitchen", {"state": "on", "brightness": 100})
        """
        await self._adapter.set(namespace, key, value)

    async def delete(self, namespace: str, key: str) -> bool:
        """
        Удалить значение.
        
        Returns:
            True если запись была удалена
        """
        return await self._adapter.delete(namespace, key)

    async def list_keys(self, namespace: str) -> list[str]:
        """
        Получить список всех ключей в namespace.
        
        Пример:
            keys = await storage.list_keys("devices")
            # ["lamp_kitchen", "sensor_bedroom", ...]
        """
        return await self._adapter.list_keys(namespace)

    async def clear_namespace(self, namespace: str) -> None:
        """Очистить все записи в namespace."""
        await self._adapter.clear_namespace(namespace)

    async def close(self) -> None:
        """Закрыть соединение."""
        await self._adapter.close()
