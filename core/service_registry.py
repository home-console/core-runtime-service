"""
ServiceRegistry - реестр сервисов для вызова методов плагинов.

Плагины регистрируют свои сервисы.
Другие плагины вызывают эти сервисы через registry.
"""

import asyncio
from typing import Any, Callable, Awaitable, List, Optional
from abc import ABC, abstractmethod


# Тип для сервисной функции
ServiceFunc = Callable[..., Awaitable[Any]]


class ServiceMiddleware(ABC):
    """
    Базовый класс для middleware сервисов.
    
    Middleware позволяет добавлять логирование, метрики, валидацию
    и другую логику вокруг вызовов сервисов.
    """
    
    @abstractmethod
    async def before_call(self, service_name: str, args: tuple, kwargs: dict) -> None:
        """
        Вызывается перед вызовом сервиса.
        
        Args:
            service_name: имя сервиса
            args: позиционные аргументы
            kwargs: именованные аргументы
        """
        pass
    
    @abstractmethod
    async def after_call(self, service_name: str, result: Any) -> None:
        """
        Вызывается после успешного вызова сервиса.
        
        Args:
            service_name: имя сервиса
            result: результат выполнения сервиса
        """
        pass
    
    @abstractmethod
    async def on_error(self, service_name: str, error: Exception) -> None:
        """
        Вызывается при ошибке в сервисе.
        
        Args:
            service_name: имя сервиса
            error: исключение, возникшее при вызове
        """
        pass


class ServiceRegistry:
    """
    Реестр сервисов для между плагинов взаимодействия.
    
    Принцип работы:
    - плагины регистрируют сервисы (методы)
    - другие плагины вызывают эти сервисы по имени
    - ServiceRegistry маршрутизирует вызовы
    - Все вызовы защищены timeout по умолчанию
    """

    def __init__(self, default_timeout: Optional[float] = None):
        """
        Инициализация ServiceRegistry.
        
        Args:
            default_timeout: дефолтный timeout для вызовов сервисов (секунды).
                           Если None, timeout не применяется (для обратной совместимости).
        """
        # Словарь: service_name -> function
        self._services: dict[str, ServiceFunc] = {}
        # Словарь: service_name.version -> deprecated flag
        self._deprecated: dict[str, bool] = {}
        # Lock для thread-safety операций с _services
        self._lock = asyncio.Lock()
        # Дефолтный timeout для всех вызовов
        self._default_timeout: Optional[float] = default_timeout

    async def register(self, service_name: str, func: ServiceFunc, version: Optional[str] = None) -> None:
        """
        Зарегистрировать сервис.
        
        Args:
            service_name: имя сервиса (например, "devices.turn_on")
            func: async функция-обработчик
            version: опциональная версия API (например, "v1", "v2")
            
        Пример:
            async def turn_on_device(device_id: str):
                # логика включения устройства
                pass
            
            await service_registry.register("devices.turn_on", turn_on_device)
            await service_registry.register("devices.turn_on", turn_on_device_v2, version="v2")
        """
        # Если указана версия, добавляем её к имени сервиса
        if version:
            versioned_name = f"{service_name}.{version}"
        else:
            versioned_name = service_name
        
        async with self._lock:
            if versioned_name in self._services:
                raise ValueError(f"Сервис '{versioned_name}' уже зарегистрирован")
            self._services[versioned_name] = func
            # По умолчанию сервис не deprecated
            self._deprecated[versioned_name] = False
    
    async def register_with_middleware(
        self,
        service_name: str,
        func: ServiceFunc,
        middleware: List[ServiceMiddleware]
    ) -> None:
        """
        Зарегистрировать сервис с middleware.
        
        Args:
            service_name: имя сервиса
            func: async функция-обработчик
            middleware: список middleware для применения
            
        Пример:
            class LoggingMiddleware(ServiceMiddleware):
                async def before_call(self, service_name, args, kwargs):
                    print(f"Calling {service_name}")
                
                async def after_call(self, service_name, result):
                    print(f"{service_name} returned {result}")
                
                async def on_error(self, service_name, error):
                    print(f"{service_name} failed: {error}")
            
            await service_registry.register_with_middleware(
                "devices.turn_on",
                turn_on_device,
                [LoggingMiddleware()]
            )
        """
        async def wrapped(*args, **kwargs):
            # Вызываем before_call для всех middleware
            for m in middleware:
                await m.before_call(service_name, args, kwargs)
            
            try:
                result = await func(*args, **kwargs)
                # Вызываем after_call для всех middleware
                for m in middleware:
                    await m.after_call(service_name, result)
                return result
            except Exception as e:
                # Вызываем on_error для всех middleware
                for m in middleware:
                    await m.on_error(service_name, e)
                raise
        
        await self.register(service_name, wrapped)

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
            asyncio.TimeoutError: если вызов превысил timeout (если установлен default_timeout)
            
        Пример:
            result = await service_registry.call("devices.turn_on", "lamp_kitchen")
        
        SECURITY NOTE: ServiceRegistry не выполняет проверки авторизации. Сервисы считаются trusted.
        Authorization выполняется на boundary-слое (ApiModule, AdminModule) перед вызовом сервисов.
        Прямые вызовы через service_registry.call() допустимы только из trusted-кода (модулей и плагинов).
        
        TIMEOUT NOTE: Если установлен default_timeout, все вызовы защищены timeout автоматически.
        """
        # Получаем функцию под lock для thread-safety
        async with self._lock:
            func = self._services.get(service_name)
            if func is None:
                raise ValueError(f"Сервис '{service_name}' не найден")
        
        # Вызываем функцию вне lock, чтобы не блокировать другие вызовы
        # Если установлен default_timeout, применяем его
        if self._default_timeout is not None:
            return await asyncio.wait_for(
                func(*args, **kwargs),
                timeout=self._default_timeout
            )
        else:
            return await func(*args, **kwargs)
    
    async def call_with_timeout(
        self,
        service_name: str,
        timeout: float,
        *args,
        **kwargs
    ) -> Any:
        """
        Вызвать сервис с timeout.
        
        Args:
            service_name: имя сервиса
            timeout: timeout в секундах
            *args, **kwargs: аргументы для сервиса
            
        Returns:
            Результат выполнения сервиса
            
        Raises:
            ValueError: если сервис не найден
            asyncio.TimeoutError: если вызов превысил timeout
            
        Пример:
            result = await service_registry.call_with_timeout(
                "devices.turn_on",
                timeout=5.0,
                "lamp_kitchen"
            )
        """
        return await asyncio.wait_for(
            self.call(service_name, *args, **kwargs),
            timeout=timeout
        )

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
            self._deprecated.clear()
    
    async def get_versions(self, service_name: str) -> list[str]:
        """
        Получить список всех версий для сервиса.
        
        Args:
            service_name: имя сервиса (например, "devices.list")
        
        Returns:
            Список версий (например, ["v1", "v2"])
        
        Пример:
            versions = await service_registry.get_versions("devices.list")
            # Вернёт ["v1", "v2"] если есть devices.list.v1 и devices.list.v2
        """
        async with self._lock:
            versions = []
            for registered_name in self._services.keys():
                if registered_name == service_name:
                    # Сервис без версии
                    versions.append("")
                elif registered_name.startswith(f"{service_name}."):
                    # Извлекаем версию из имени
                    version = registered_name[len(service_name) + 1:]
                    if version not in versions:
                        versions.append(version)
            return sorted(versions)
    
    async def is_deprecated(self, service_name: str, version: Optional[str] = None) -> bool:
        """
        Проверить, является ли версия сервиса устаревшей.
        
        Args:
            service_name: имя сервиса
            version: версия API (если None, проверяет сервис без версии)
        
        Returns:
            True если версия помечена как deprecated
        
        Пример:
            if await service_registry.is_deprecated("devices.list", "v1"):
                print("Версия v1 устарела, используйте v2")
        """
        async with self._lock:
            if version:
                versioned_name = f"{service_name}.{version}"
            else:
                versioned_name = service_name
            return self._deprecated.get(versioned_name, False)
    
    async def mark_deprecated(self, service_name: str, version: Optional[str] = None) -> None:
        """
        Пометить версию сервиса как устаревшую.
        
        Args:
            service_name: имя сервиса
            version: версия API (если None, помечает сервис без версии)
        
        Raises:
            ValueError: если сервис не найден
        
        Пример:
            await service_registry.mark_deprecated("devices.list", "v1")
        """
        async with self._lock:
            if version:
                versioned_name = f"{service_name}.{version}"
            else:
                versioned_name = service_name
            
            if versioned_name not in self._services:
                raise ValueError(f"Сервис '{versioned_name}' не найден")
            
            self._deprecated[versioned_name] = True