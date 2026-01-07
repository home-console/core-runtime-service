"""
PluginManager - управление lifecycle плагинов.

Загружает, запускает, останавливает плагины.
"""

from typing import Optional, TYPE_CHECKING
from enum import Enum

from plugins.base_plugin import BasePlugin, PluginMetadata

if TYPE_CHECKING:
    from core.runtime import CoreRuntime


class PluginState(Enum):
    """Состояния плагина."""
    UNLOADED = "unloaded"
    LOADED = "loaded"
    STARTED = "started"
    STOPPED = "stopped"
    ERROR = "error"


class PluginManager:
    """
    Менеджер для управления lifecycle плагинов.
    
    Отвечает за:
    - загрузку плагинов
    - запуск плагинов
    - остановку плагинов
    - отслеживание состояния
    """

    def __init__(self, runtime: Optional["CoreRuntime"] = None):
        # Ссылка на CoreRuntime, может быть не установлена (тесты создают PluginManager() без runtime)
        self._runtime = runtime
        # Словарь: plugin_name -> plugin_instance
        self._plugins: dict[str, BasePlugin] = {}
        # Словарь: plugin_name -> state
        self._states: dict[str, PluginState] = {}

    async def load_plugin(self, plugin: BasePlugin) -> None:
        """
        Загрузить плагин.
        
        Args:
            plugin: экземпляр плагина
            
        Raises:
            ValueError: если плагин уже загружен
        """
        # Получить имя плагина заранее для error handling
        # Читаем metadata ДО on_load, чтобы иметь plugin_name в случае ошибки
        metadata = plugin.metadata
        plugin_name = metadata.name
        
        # Установим ссылку на runtime у плагина перед вызовом on_load
        try:
            try:
                # Мgr может хранить Optional runtime; приводим к CoreRuntime
                # для подавления предупреждений типизации (архитектурный контракт).
                from typing import cast

                plugin.runtime = cast("CoreRuntime", self._runtime)
            except Exception:
                # Установка runtime не должна ломать загрузку
                pass

            # Вызов on_load может обновить metadata (например, remote proxy)
            await plugin.on_load()

            # Заново прочитаем metadata после on_load в случае, если она изменилась
            metadata = plugin.metadata
            plugin_name = metadata.name

            if plugin_name in self._plugins:
                raise ValueError(f"Плагин '{plugin_name}' уже загружен")

            # Проверить зависимости, указанные в metadata после on_load
            for dep_name in metadata.dependencies:
                if dep_name not in self._plugins:
                    raise ValueError(
                        f"Плагин '{plugin_name}' требует плагин '{dep_name}', "
                        f"но он не загружен"
                    )

            self._plugins[plugin_name] = plugin
            self._states[plugin_name] = PluginState.LOADED
        except Exception as e:
            # Устанавливаем состояние ERROR
            self._states[plugin_name] = PluginState.ERROR
            # Пробросываем оригинальное исключение, чтобы тесты могли его ловить
            raise

    async def start_plugin(self, plugin_name: str) -> None:
        """
        Запустить плагин.
        
        Args:
            plugin_name: имя плагина
            
        Raises:
            ValueError: если плагин не найден или не загружен
        """
        plugin = self._plugins.get(plugin_name)
        if plugin is None:
            raise ValueError(f"Плагин '{plugin_name}' не найден")
        
        if self._states[plugin_name] == PluginState.STARTED:
            return  # Уже запущен
        
        try:
            await plugin.on_start()
            self._states[plugin_name] = PluginState.STARTED
        except Exception as e:
            self._states[plugin_name] = PluginState.ERROR
            raise RuntimeError(f"Ошибка запуска плагина '{plugin_name}': {e}")

    async def stop_plugin(self, plugin_name: str) -> None:
        """
        Остановить плагин.
        
        Args:
            plugin_name: имя плагина
            
        Raises:
            ValueError: если плагин не найден
        """
        plugin = self._plugins.get(plugin_name)
        if plugin is None:
            raise ValueError(f"Плагин '{plugin_name}' не найден")
        
        if self._states[plugin_name] != PluginState.STARTED:
            return  # Не запущен
        
        try:
            await plugin.on_stop()
            self._states[plugin_name] = PluginState.STOPPED
        except Exception as e:
            self._states[plugin_name] = PluginState.ERROR
            raise RuntimeError(f"Ошибка остановки плагина '{plugin_name}': {e}")

    async def unload_plugin(self, plugin_name: str) -> None:
        """
        Выгрузить плагин.
        
        Args:
            plugin_name: имя плагина
            
        Raises:
            ValueError: если плагин не найден
        """
        plugin = self._plugins.get(plugin_name)
        if plugin is None:
            raise ValueError(f"Плагин '{plugin_name}' не найден")
        
        # Сначала остановить, если запущен
        if self._states[plugin_name] == PluginState.STARTED:
            await self.stop_plugin(plugin_name)
        
        try:
            await plugin.on_unload()
            del self._plugins[plugin_name]
            self._states[plugin_name] = PluginState.UNLOADED
        except Exception as e:
            self._states[plugin_name] = PluginState.ERROR
            raise RuntimeError(f"Ошибка выгрузки плагина '{plugin_name}': {e}")

    def get_plugin(self, plugin_name: str) -> Optional[BasePlugin]:
        """
        Получить экземпляр плагина.
        
        Args:
            plugin_name: имя плагина
            
        Returns:
            Экземпляр плагина или None
        """
        return self._plugins.get(plugin_name)

    def get_plugin_state(self, plugin_name: str) -> Optional[PluginState]:
        """
        Получить состояние плагина.
        
        Args:
            plugin_name: имя плагина
            
        Returns:
            Состояние плагина или None
        """
        return self._states.get(plugin_name)

    def list_plugins(self) -> list[str]:
        """
        Получить список всех загруженных плагинов.
        
        Returns:
            Список имён плагинов
        """
        return list(self._plugins.keys())

    async def start_all(self) -> None:
        """Запустить все загруженные плагины."""
        for plugin_name in self._plugins.keys():
            if self._states[plugin_name] == PluginState.LOADED:
                await self.start_plugin(plugin_name)

    async def stop_all(self) -> None:
        """Остановить все запущенные плагины."""
        for plugin_name in self._plugins.keys():
            if self._states[plugin_name] == PluginState.STARTED:
                await self.stop_plugin(plugin_name)
