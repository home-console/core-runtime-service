"""
Service Registry Models — middleware and type definitions .

Декларативные модели для middleware и типизация функций-сервисов.
"""

from dataclasses import dataclass
from typing import Any, Callable, Awaitable, Optional, Sequence
from abc import ABC, abstractmethod


# Тип для сервисной функции
ServiceFunc = Callable[..., Awaitable[Any]]


@dataclass(frozen=True)
class ServiceAuthConfig:
    """
    Декларативная конфигурация авторизации для runtime-сервиса.

    Зачем:
    - HTTP/WS маршруты и любые вызовы сервисов снаружи процесса должны
      иметь единый источник правды о доступе.
    - Плагины и модули должны объявлять доступ рядом с регистрацией сервиса,
      чтобы не требовать ручных правок центрального authz mapping.
    """

    public: bool = False
    required_scopes: Optional[Sequence[str]] = None


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
