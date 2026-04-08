"""
AppConfig — app-level конфигурация для extension hooks.

Вынесено из core.runtime.runtime для соблюдения границ ядра.
App-level extension hooks принадлежат app-layer, не минимальному kernel.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Optional, List


@dataclass
class AppExtensionConfig:
    """
    Конфигурация app-level extension hooks.

    Атрибуты:
        event_validation_middleware_factory: фабрика middleware для валидации событий
        plugin_storage_proxy_cls: класс прокси для storage плагинов
        plugin_service_proxy_cls: класс прокси для сервисов плагинов
        plugin_default_allowed_services: список разрешённых сервисов для плагинов по умолчанию
    """
    event_validation_middleware_factory: Optional[Callable[[], Any]] = None
    plugin_storage_proxy_cls: Optional[type] = None
    plugin_service_proxy_cls: Optional[type] = None
    plugin_default_allowed_services: List[str] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        event_validation_middleware_factory: Optional[Callable[[], Any]] = None,
        plugin_storage_proxy_cls: Optional[type] = None,
        plugin_service_proxy_cls: Optional[type] = None,
        plugin_default_allowed_services: Optional[List[str]] = None,
    ) -> "AppExtensionConfig":
        """
        Создать AppExtensionConfig.

        Args:
            event_validation_middleware_factory: фабрика middleware для валидации событий
            plugin_storage_proxy_cls: класс прокси для storage плагинов
            plugin_service_proxy_cls: класс прокси для сервисов плагинов
            plugin_default_allowed_services: список разрешённых сервисов

        Returns:
            Экземпляр AppExtensionConfig
        """
        return cls(
            event_validation_middleware_factory=event_validation_middleware_factory,
            plugin_storage_proxy_cls=plugin_storage_proxy_cls,
            plugin_service_proxy_cls=plugin_service_proxy_cls,
            plugin_default_allowed_services=plugin_default_allowed_services or [],
        )
