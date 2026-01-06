"""
ServiceRegistry - реестр сервисов для вызова методов плагинов.

Плагины регистрируют свои сервисы.
Другие плагины вызывают эти сервисы через registry.
"""

from typing import Any, Callable, Awaitable, Optional


# Тип для сервисной функции
ServiceFunc = Callable[..., Awaitable[Any]]


class ServiceRegistry:
    """
    Реестр сервисов для межплагинного взаимодействия.
    
    Принцип работы:
    - плагины регистрируют сервисы (методы)
    - другие плагины вызывают эти сервисы по имени
    - ServiceRegistry маршрутизирует вызовы
    """

    def __init__(self):
        # Словарь: service_name -> function
        self._services: dict[str, ServiceFunc] = {}

    def register(self, service_name: str, func: ServiceFunc) -> None:
        """
        Зарегистрировать сервис.
        
        Args:
            service_name: имя сервиса (например, "devices.turn_on")
            func: async функция-обработчик
            
        Пример:
            async def turn_on_device(device_id: str):
                # логика включения устройства
                pass
            
            service_registry.register("devices.turn_on", turn_on_device)
        """
        if service_name in self._services:
            raise ValueError(f"Сервис '{service_name}' уже зарегистрирован")
        self._services[service_name] = func

    def unregister(self, service_name: str) -> None:
        """
        Удалить сервис из реестра.
        
        Args:
            service_name: имя сервиса
        """
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
        func = self._services.get(service_name)
        if func is None:
            raise ValueError(f"Сервис '{service_name}' не найден")
        
        return await func(*args, **kwargs)

    def has_service(self, service_name: str) -> bool:
        """
        Проверить, существует ли сервис.
        
        Args:
            service_name: имя сервиса
            
        Returns:
            True если сервис зарегистрирован
        """
        return service_name in self._services

    def list_services(self) -> list[str]:
        """
        Получить список всех зарегистрированных сервисов.
        
        Returns:
            Список имён сервисов
        """
        return list(self._services.keys())

    def clear(self) -> None:
        """Очистить все сервисы."""
        self._services.clear()
