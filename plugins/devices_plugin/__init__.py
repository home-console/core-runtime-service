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

from typing import Any, Dict

from plugins.base_plugin import BasePlugin, PluginMetadata

# Lightweight adapter: delegate devices domain to modules/devices
from modules.devices import register_devices

__all__ = ["DevicesPlugin"]


class DevicesPlugin(BasePlugin):
    """Thin adapter plugin that registers built-in devices module into runtime.

    All domain logic lives in `modules/devices`. This plugin only invokes
    `register_devices(runtime)` when loaded so PluginManager can still use it.
    """

    def __init__(self, runtime):
        super().__init__(runtime)
        self._module_unregister = None

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="devices",
            version="1.0.0",
            description="Adapter plugin that registers built-in devices module",
            author="Home Console",
        )

    async def on_load(self) -> None:
        await super().on_load()
        # Register the devices domain into the CoreRuntime
        res = register_devices(self.runtime)
        # keep unregister callable for graceful unload
        self._module_unregister = res.get("unregister") if isinstance(res, dict) else None

    async def on_unload(self) -> None:
        await super().on_unload()
        if callable(self._module_unregister):
            try:
                self._module_unregister()
            except Exception:
                pass
        self.runtime = None
