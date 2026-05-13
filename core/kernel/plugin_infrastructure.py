"""
PluginInfrastructure — инфраструктура для управления плагинами и модулями.

Отвечает за:
- Загрузку и lifecycle плагинов (plugin_manager)
- Управление модулями (module_manager)
- Dependency policy/integrity (lifecycle_policy / integrity_checker)
- Интеграции (integrations)

Этот класс инкапсулирует всю логику работы с плагинами и модулями,
освобождая CoreRuntime от этих обязанностей.
"""

import logging
from typing import Any, Optional

from core.module import ModuleManager
from core.dependency.integrity_checker import DependencyIntegrityChecker
from core.dependency.lifecycle_policy import PluginLifecyclePolicy
from core.kernel.integration_registry import IntegrationRegistry
from core.capability.registry import CapabilityRegistry
from core.exception_groups import PLUGIN_INTROSPECTION_ERRORS
from core.exception_groups import BEST_EFFORT_BACKGROUND_ERRORS

logger = logging.getLogger(__name__)


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
        runtime: Any,
        capability_registry: CapabilityRegistry,
        config: Optional[Any] = None,
    ):
        """
        Инициализация инфраструктуры плагинов.

        Args:
            runtime: экземпляр CoreRuntime (или совместимый объект), предоставляющий services/operations/http/...
            capability_registry: реестр capabilities для dependency resolver
            config: опциональная конфигурация (для module_path_prefix)
        """
        self.runtime = runtime
        self.services = getattr(runtime, "services", runtime)
        self.capability_registry = capability_registry

        # Интеграции
        self.integrations = IntegrationRegistry()

        # Plugin Manager — lifecycle плагинов
        # Передаём runtime, чтобы фасад для плагинов содержал operations/http/event_bus и т.п.
        from core.kernel.plugin_manager import PluginManager

        self.plugin_manager = PluginManager(runtime, capability_registry=capability_registry)

        # Module Manager — управление модулями
        module_path_prefix = (
            getattr(config, "module_path_prefix", "modules")
            if config is not None
            else "modules"
        )
        self.module_manager = ModuleManager(runtime, module_path_prefix=module_path_prefix)

        # Dependency components — явные контракты вместо facade/shims
        self.integrity_checker = DependencyIntegrityChecker(
            capability_registry=capability_registry,
            plugin_manager=self.plugin_manager,
        )
        self.lifecycle_policy = PluginLifecyclePolicy(
            capability_registry=capability_registry,
            plugin_manager=self.plugin_manager,
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
            "integrity_checker": self.integrity_checker,
            "lifecycle_policy": self.lifecycle_policy,
            "integrations": self.integrations,
        }


class PluginInfrastructureCoordinator:
    """Coordinates plugin-related registrations across runtime subsystems."""

    def __init__(
        self,
        capability_registry: Optional[Any] = None,
        operations: Optional[Any] = None,
        integrations: Optional[Any] = None,
    ):
        self._capability_registry = capability_registry
        self._operations = operations
        self._integrations = integrations

    async def on_plugin_loaded(self, plugin: Any) -> None:
        """Register capabilities/handlers/integration metadata when plugin is loaded."""
        metadata = getattr(plugin, "metadata", None)
        if metadata is None:
            return

        plugin_name = getattr(metadata, "name", None)
        if not plugin_name:
            return

        if self._capability_registry is not None:
            # Register provided capabilities
            provider_type = "remote" if getattr(metadata, "remote_config", None) else "local"
            execution_mode = str(getattr(metadata, "execution_mode", "in_process") or "in_process")
            remote_config = getattr(metadata, "remote_config", None)
            process_config = getattr(metadata, "process_config", None)
            container_config = getattr(metadata, "container_config", None)
            for capability in getattr(metadata, "capabilities_provided", []) or []:
                try:
                    await self._capability_registry.register_provider(
                        plugin_name,
                        capability,
                        provider_type=provider_type,
                        remote_config=remote_config,
                        execution_mode=execution_mode,
                        process_config=process_config,
                        container_config=container_config,
                    )
                except BEST_EFFORT_BACKGROUND_ERRORS as e:
                    if isinstance(e, PLUGIN_INTROSPECTION_ERRORS):
                        logger.debug(
                            "on_plugin_loaded: register_provider failed for %s / %s",
                            plugin_name,
                            capability,
                            exc_info=True,
                        )
                    else:
                        logger.warning(
                            "on_plugin_loaded: register_provider unexpected for %s / %s",
                            plugin_name,
                            capability,
                            exc_info=True,
                        )
            
            # Register required capabilities (consumer)
            for capability in getattr(metadata, "capabilities_required", []) or []:
                try:
                    await self._capability_registry.register_consumer(plugin_name, capability)
                except BEST_EFFORT_BACKGROUND_ERRORS as e:
                    if isinstance(e, PLUGIN_INTROSPECTION_ERRORS):
                        logger.debug(
                            "on_plugin_loaded: register_consumer failed for %s / %s",
                            plugin_name,
                            capability,
                            exc_info=True,
                        )
                    else:
                        logger.warning(
                            "on_plugin_loaded: register_consumer unexpected for %s / %s",
                            plugin_name,
                            capability,
                            exc_info=True,
                        )

        # operations are registered by plugins via runtime API; nothing to do here.
        # integrations are handled by PluginManager via manifest flags.

    async def on_plugin_unloaded(self, plugin: Any) -> None:
        """Cleanup capabilities/handlers/integration metadata when plugin is unloaded."""
        metadata = getattr(plugin, "metadata", None)
        if metadata is None:
            return

        plugin_name = getattr(metadata, "name", None)
        if not plugin_name:
            return

        if self._capability_registry is not None:
            try:
                await self._capability_registry.unregister_plugin(plugin_name)
            except BEST_EFFORT_BACKGROUND_ERRORS as e:
                if isinstance(e, PLUGIN_INTROSPECTION_ERRORS):
                    logger.debug(
                        "on_plugin_unloaded: unregister_plugin failed for %s",
                        plugin_name,
                        exc_info=True,
                    )
                else:
                    logger.warning(
                        "on_plugin_unloaded: unregister_plugin unexpected for %s",
                        plugin_name,
                        exc_info=True,
                    )

        if self._operations is not None:
            for op_type in getattr(metadata, "capabilities_provided", []) or []:
                try:
                    self._operations.unregister_handler(op_type)
                except BEST_EFFORT_BACKGROUND_ERRORS as e:
                    if isinstance(e, PLUGIN_INTROSPECTION_ERRORS):
                        logger.debug(
                            "on_plugin_unloaded: unregister_handler failed for %s / %s",
                            plugin_name,
                            op_type,
                            exc_info=True,
                        )
                    else:
                        logger.warning(
                            "on_plugin_unloaded: unregister_handler unexpected for %s / %s",
                            plugin_name,
                            op_type,
                            exc_info=True,
                        )
