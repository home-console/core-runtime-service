"""
BasePlugin — контракт плагина (ABC).

runtime — opaque объект (PluginRuntime). Lifecycle вызывается только Core.
Плагин не управляет собой.
"""

from abc import ABC, abstractmethod
from typing import Optional

from sdk.context import PluginRuntime
from sdk.metadata import PluginMetadata


class BasePlugin(ABC):
    """
    Базовый класс для всех плагинов.
    Lifecycle: on_load → on_start → on_stop → on_unload (вызывает только Core).
    """

    def __init__(self, runtime: Optional[PluginRuntime] = None) -> None:
        """
        Инициализация плагина.
        runtime устанавливается менеджером плагинов перед вызовом lifecycle.
        """
        self._runtime: Optional[PluginRuntime] = runtime

    @property
    def runtime(self) -> PluginRuntime:
        """Среда выполнения. Гарантированно установлена при вызове on_load/on_start/on_stop/on_unload."""
        if self._runtime is None:
            raise RuntimeError("Plugin runtime not set")
        return self._runtime

    @runtime.setter
    def runtime(self, value: Optional[PluginRuntime]) -> None:
        self._runtime = value

    @property
    @abstractmethod
    def metadata(self) -> PluginMetadata:
        """Метаданные плагина. Обязательны к реализации."""
        ...

    async def on_load(self) -> None:
        """
        Вызывается Core при загрузке.
        Здесь: регистрация сервисов, capabilities, operations handlers.
        """
        pass

    async def on_start(self) -> None:
        """
        Вызывается Core при запуске.
        Здесь: фоновые задачи, подписки на события.
        """
        pass

    async def on_stop(self) -> None:
        """
        Вызывается Core при остановке.
        Здесь: отмена фоновых задач.
        """
        pass

    async def on_unload(self) -> None:
        """
        Вызывается Core при выгрузке.
        Здесь: очистка ресурсов.
        """
        pass
