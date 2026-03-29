"""
Service Registry Models — middleware and type definitions .

Декларативные модели для middleware и типизация функций-сервисов.
"""

from typing import Any, Callable, Awaitable
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
