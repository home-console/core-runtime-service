"""
PluginInfrastructureCoordinator — координация инфраструктурных привязок плагинов.

Задачи:
- Регистрация capabilities плагина в CapabilityRegistry при загрузке
- Регистрация потребления capabilities (consumers)
- Дерегистрация capabilities и связанных handler'ов при выгрузке
- Дерегистрация интеграций, привязанных к плагину, из IntegrationRegistry

Важно:
- Этот класс НЕ знает про PluginRegistry и не управляет lifecycle плагинов.
- Его ответственность — только инфраструктурные побочные эффекты вокруг плагина.
"""

from __future__ import annotations

from typing import Optional, Any

from core.base_plugin import BasePlugin, PluginMetadata
from core.capability_registry import CapabilityRegistry
from core.operations.manager import OperationManager
from core.integration_registry import IntegrationRegistry


class PluginInfrastructureCoordinator:
    """
    Координатор инфраструктуры вокруг плагинов.

    Инкапсулирует:
    - Регистрацию/дерегистрацию capabilities в CapabilityRegistry
    - Очистку operation handler'ов, связанных с capabilities плагина
    - Очистку записей об интеграциях в IntegrationRegistry
    """

    def __init__(
        self,
        *,
        capability_registry: Optional[CapabilityRegistry] = None,
        operations: Optional[OperationManager] = None,
        integrations: Optional[IntegrationRegistry] = None,
    ) -> None:
        self._cap_reg = capability_registry
        self._ops = operations
        self._integrations = integrations

    def _has_capabilities(self) -> bool:
        return self._cap_reg is not None

    async def on_plugin_loaded(self, plugin: BasePlugin) -> None:
        """
        Обработать инфраструктурные привязки при загрузке плагина.

        - Зарегистрировать provided capabilities в CapabilityRegistry
        - Зарегистрировать required capabilities как consumers
        """
        if not self._has_capabilities():
            return

        cap_reg = self._cap_reg  # type: ignore[assignment]
        metadata: PluginMetadata = plugin.metadata
        plugin_name = metadata.name

        # Trust-aware capability registration
        trust_level = getattr(plugin, "_trust_level", None)
        plugin_privilege = cap_reg.trust_level_to_privilege(trust_level)

        for cap_id in (metadata.capabilities_provided or []):
            provider_type = "remote" if metadata.remote_config else "local"
            await cap_reg.register_provider(
                plugin_name,
                cap_id,
                provider_type=provider_type,
                remote_config=metadata.remote_config,
                plugin_privilege=plugin_privilege,
            )

        for cap_id in (metadata.capabilities_required or []):
            await cap_reg.register_consumer(plugin_name, cap_id)

    async def on_plugin_unloaded(self, plugin: BasePlugin) -> None:
        """
        Обработать инфраструктурную очистку при выгрузке плагина.

        - Снять handler'ы операций, завязанные на capabilities плагина
        - Удалить записи о capabilities плагина из CapabilityRegistry
        - Удалить связанные интеграции из IntegrationRegistry
        """
        metadata: PluginMetadata = plugin.metadata
        plugin_name = metadata.name

        # 1. Очистка operation handler'ов (legacy привязка по capability / имени плагина)
        if self._ops is not None:
            for cap_id in metadata.capabilities_provided:
                # Unregister direct handler (backward compatibility)
                self._ops.unregister_handler(cap_id)
                # Unregister plugin name as handler (if it was used)
                self._ops.unregister_handler(plugin_name)

        # 2. Удаление capabilities из CapabilityRegistry
        if self._cap_reg is not None:
            await self._cap_reg.unregister_plugin(plugin_name)

        # 3. Удаление интеграций, связанных с этим плагином
        if self._integrations is not None:
            # IntegrationRegistry хранит mapping integration_id -> info(plugin_name=...)
            for info in list(self._integrations.list_by_plugin(plugin_name)):
                self._integrations.unregister(info.id)

