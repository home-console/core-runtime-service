"""
Пакет `plugins.devices_plugin`

Здесь находится реализация класса `DevicesPlugin`. Ранее реализация была в
`plugins/devices_plugin.py` (модуль). Реализация перенесена в пакет, чтобы
разбить логику на подмодули (`devices_lifecycle`, `devices_services`, ...)
и упростить дальнейшую реорганизацию/тестирование.

Совместимость:
- Импорт `from plugins.devices_plugin import DevicesPlugin` продолжает работать.
- После проверки и обновления всех импортов старый модуль `plugins/devices_plugin.py`
  можно удалить (оставить при необходимости shim-версию, которая будет
  импортировать класс из этого пакета и выдавать DeprecationWarning).
"""

from typing import Any, Dict, List, Optional

from plugins.base_plugin import BasePlugin, PluginMetadata
from plugins.devices_plugin import devices_lifecycle as lifecycle  # noqa: WPS433
from plugins.devices_plugin import devices_services as services

__all__ = ["DevicesPlugin"]


class DevicesPlugin(BasePlugin):
    """Плагин для управления устройствами (делегирует реализацию в модули)."""

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="devices",
            version="1.0.0",
            description="Плагин для хранения и управления устройствами",
            author="Home Console",
        )

    async def on_load(self) -> None:
        await super().on_load()
        # Импорт внутри метода — чтобы избежать циклических импортов при загрузке пакета
        await lifecycle.on_load(self)

    async def on_start(self) -> None:
        await super().on_start()
        await lifecycle.on_start(self)

    async def on_stop(self) -> None:
        await super().on_stop()
        await lifecycle.on_stop(self)

    async def on_unload(self) -> None:
        await super().on_unload()
        await lifecycle.on_unload(self)

    # ========== СЕРВИСЫ ==========

    async def create_device(
        self,
        device_id: str,
        name: str = "Unknown",
        device_type: str = "generic",
    ) -> Dict[str, Any]:
        return await services.create_device(self, device_id, name, device_type)

    async def set_state(self, device_id: str, state: Dict[str, Any]) -> Dict[str, Any]:
        return await services.set_state(self, device_id, state)

    async def list_devices(self) -> List[Dict[str, Any]]:
        return await services.list_devices(self)

    async def get_device(self, device_id: str) -> Dict[str, Any]:
        return await services.get_device(self, device_id)

    async def list_external(
        self, provider: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        return await services.list_external(self, provider)

    async def create_mapping(
        self,
        external_id: str,
        internal_id: str,
    ) -> Dict[str, Any]:
        return await services.create_mapping(self, external_id, internal_id)

    async def list_mappings(self) -> List[Dict[str, Any]]:
        return await services.list_mappings(self)

    async def delete_mapping(self, external_id: str) -> Dict[str, Any]:
        return await services.delete_mapping(self, external_id)

    async def auto_map_external(self, provider: Optional[str] = None) -> Dict[str, Any]:
        return await services.auto_map_external(self, provider)
