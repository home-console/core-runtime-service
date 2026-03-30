"""
PluginInfrastructure — инфраструктура для управления плагинами и модулями.

Отвечает за:
- Загрузку и lifecycle плагинов (plugin_manager)
- Управление модулями (module_manager)
- Разрешение зависимостей (dependency_resolver)
- Интеграции (integrations)

Этот класс инкапсулирует всю логику работы с плагинами и модулями,
освобождая CoreRuntime от этих обязанностей.
"""

from typing import Any, Optional

from core.kernel.plugin_manager import PluginManager
from core.module import ModuleManager
from core.dependency.resolver import DependencyResolver
from core.kernel.integration_registry import IntegrationRegistry
from core.capability.registry import CapabilityRegistry


class PluginInfrastructure:
    """
    Инфраструктура для управления плагинами и модулями.

    Отвечает за:
    - Загрузку и lifecycle плагинов
    - Управление модулями
    - Разрешение зависимостей
    - Интеграции

    Использование:
        plugin_infra = PluginInfrastructure(services, capability_registry, config)
        await plugin_infra.plugin_manager.load_plugin(plugin)
        await plugin_infra.module_manager.register_module_specs(runtime, specs)
    """

    def __init__(
        self,
        services: Any,
        capability_registry: CapabilityRegistry,
        config: Optional[Any] = None,
    ):
        """
        Инициализация инфраструктуры плагинов.

        Args:
            services: экземпляр CoreServices (предоставляет storage, event_bus, service_registry)
            capability_registry: реестр capabilities для dependency resolver
            config: опциональная конфигурация (для module_path_prefix)
        """
        self.services = services

        # Интеграции
        self.integrations = IntegrationRegistry()

        # Plugin Manager — lifecycle плагинов
        # Передаём services как runtime (плагинам нужен доступ к сервисам)
        self.plugin_manager = PluginManager(services)

        # Module Manager — управление модулями
        module_path_prefix = (
            getattr(config, "module_path_prefix", "modules")
            if config is not None
            else "modules"
        )
        self.module_manager = ModuleManager(services, module_path_prefix=module_path_prefix)

        # Dependency Resolver — разрешение зависимостей между плагинами
        self.dependency_resolver = DependencyResolver(
            capability_registry,
            self.plugin_manager,
            services.storage
        )

    def create_context(self) -> dict[str, Any]:
        """
        Создать контекст инфраструктуры плагинов.

        Возвращает основные компоненты для работы с плагинами и модулями.

        Returns:
            Словарь с компонентами инфраструктуры
        """
        return {
            "plugin_manager": self.plugin_manager,
            "module_manager": self.module_manager,
            "dependency_resolver": self.dependency_resolver,
            "integrations": self.integrations,
        }
