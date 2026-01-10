"""
ServiceRegistry - реестр сервисов для вызова методов плагинов.

Плагины регистрируют свои сервисы.
Другие плагины вызывают эти сервисы через registry.
"""

import asyncio
from typing import Any, Callable, Awaitable


# Тип для сервисной функции
ServiceFunc = Callable[..., Awaitable[Any]]


class ServiceRegistry:
    """
    Реестр сервисов для между плагинов взаимодействия.
    
    Принцип работы:
    - плагины регистрируют сервисы (методы)
    - другие плагины вызывают эти сервисы по имени
    - ServiceRegistry маршрутизирует вызовы
    """

    def __init__(self):
        # Словарь: service_name -> function
        self._services: dict[str, ServiceFunc] = {}
        # Lock для thread-safety операций с _services
        self._lock = asyncio.Lock()

    async def register(self, service_name: str, func: ServiceFunc) -> None:
        """
        Зарегистрировать сервис.
        
        Args:
            service_name: имя сервиса (например, "devices.turn_on")
            func: async функция-обработчик
            
        Пример:
            async def turn_on_device(device_id: str):
                # логика включения устройства
                pass
            
            await service_registry.register("devices.turn_on", turn_on_device)
        """
        async with self._lock:
            if service_name in self._services:
                raise ValueError(f"Сервис '{service_name}' уже зарегистрирован")
            self._services[service_name] = func

    async def unregister(self, service_name: str) -> None:
        """
        Удалить сервис из реестра.
        
        Args:
            service_name: имя сервиса
        """
        async with self._lock:
            self._services.pop(service_name, None)

    async def call(self, service_name: str, *args, **kwargs) -> Any:
        """
        Вызвать сервис.
        
        Args:
            service_name: имя сервиса
            *args, **kwargs: аргументы для сервиса
            
        Returns:
            Результат выполнения сервиса
            
        Raises:
            ValueError: если сервис не найден
            
        Пример:
            result = await service_registry.call("devices.turn_on", "lamp_kitchen")
        """
        # Получаем функцию под lock для thread-safety
        async with self._lock:
            func = self._services.get(service_name)
            if func is None:
                raise ValueError(f"Сервис '{service_name}' не найден")
        
        # Вызываем функцию вне lock, чтобы не блокировать другие вызовы
        return await func(*args, **kwargs)

    async def has_service(self, service_name: str) -> bool:
        """
        Проверить, существует ли сервис.
        
        Args:
            service_name: имя сервиса
            
        Returns:
            True если сервис зарегистрирован
        """
        async with self._lock:
            return service_name in self._services

    async def list_services(self) -> list[str]:
        """
        Получить список всех зарегистрированных сервисов.
        
        Returns:
            Список имён сервисов
        """
        async with self._lock:
            return list(self._services.keys())

    async def clear(self) -> None:
        """Очистить все сервисы."""
        async with self._lock:
            self._services.clear()
