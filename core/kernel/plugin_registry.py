"""
PluginRegistry - реестр плагинов и отслеживание состояния.

Отвечает за:
- Хранение экземпляров плагинов
- Отслеживание состояний плагинов
- Хранение причин блокировки
- Query методы для получения информации о плагинах
"""

import asyncio
from typing import Optional, Dict, Any

from enum import Enum
from core.kernel.base_plugin import BasePlugin


class PluginState(Enum):
    """Состояния плагина."""
    UNLOADED = "unloaded"
    LOADED = "loaded"
    STARTED = "started"
    STOPPED = "stopped"
    ERROR = "error"


class PluginRegistry:
    """
    Реестр плагинов.
    
    Хранит экземпляры плагинов и их состояния.
    Async-safe: использует asyncio.Lock (не threading.Lock) для избежания блокировки event loop.
    """
    
    def __init__(self):
        """Инициализация реестра."""
        # Словарь: plugin_name -> plugin_instance
        self._plugins: Dict[str, BasePlugin] = {}
        # Словарь: plugin_name -> state
        self._states: Dict[str, str] = {}
        # Причина блокировки старта (missing capabilities): plugin_name -> {"missing_capabilities": [...]}
        self._block_reasons: Dict[str, Dict[str, Any]] = {}
        # asyncio.Lock — не блокирует event loop при ожидании
        self._plugin_lock = asyncio.Lock()
    
    async def register(
        self,
        name: str,
        plugin: BasePlugin,
        state: PluginState = PluginState.LOADED
    ) -> None:
        """
        Зарегистрировать плагин в реестре.
        
        Args:
            name: имя плагина
            plugin: экземпляр плагина
            state: начальное состояние
        """
        async with self._plugin_lock:
            if name in self._plugins:
                raise ValueError(f"Плагин '{name}' уже зарегистрирован")
            self._plugins[name] = plugin
            self._states[name] = state.value
    
    async def unregister(self, name: str) -> None:
        """
        Удалить плагин из реестра.
        
        Плагин удаляется из активного реестра, но состояние остаётся как UNLOADED.
        Это позволяет запрашивать состояние после выгрузки.
        
        Args:
            name: имя плагина
        """
        async with self._plugin_lock:
            self._plugins.pop(name, None)
            # Устанавливаем UNLOADED вместо удаления записи
            self._states[name] = PluginState.UNLOADED.value
            self._block_reasons.pop(name, None)
    
    async def get_plugin(self, plugin_name: str) -> Optional[BasePlugin]:
        """
        Получить экземпляр плагина.
        
        Args:
            plugin_name: имя плагина
            
        Returns:
            Экземпляр плагина или None
        """
        async with self._plugin_lock:
            return self._plugins.get(plugin_name)
    
    async def get_plugin_state(self, plugin_name: str) -> Optional[PluginState]:
        """
        Получить состояние плагина.
        
        Args:
            plugin_name: имя плагина
            
        Returns:
            Состояние плагина или None
        """
        async with self._plugin_lock:
            state_str = self._states.get(plugin_name)
            if state_str is None:
                return None
            return PluginState(state_str)
    
    async def set_plugin_state(self, plugin_name: str, state: PluginState) -> None:
        """
        Установить состояние плагина.
        
        Args:
            plugin_name: имя плагина
            state: новое состояние
        """
        async with self._plugin_lock:
            # Разрешаем установку состояния ERROR даже если плагин не зарегистрирован
            # (например при ошибке загрузки до register())
            if plugin_name in self._plugins or state == PluginState.ERROR:
                self._states[plugin_name] = state.value
    
    async def get_plugin_block_reason(self, plugin_name: str) -> Optional[Dict[str, Any]]:
        """
        Причина, по которой плагин не стартовал (например, отсутствующие capabilities).

        Args:
            plugin_name: имя плагина
        
        Returns:
            None если плагин стартовал или не загружен.
            Иначе dict, например {"missing_capabilities": ["oauth:yandex"]}.
        """
        async with self._plugin_lock:
            return self._block_reasons.get(plugin_name)
    
    async def set_plugin_block_reason(self, plugin_name: str, reason: Dict[str, Any]) -> None:
        """
        Установить причину блокировки плагина.
        
        Args:
            plugin_name: имя плагина
            reason: причина блокировки
        """
        async with self._plugin_lock:
            self._block_reasons[plugin_name] = reason
    
    async def clear_plugin_block_reason(self, plugin_name: str) -> None:
        """
        Очистить причину блокировки плагина.
        
        Args:
            plugin_name: имя плагина
        """
        async with self._plugin_lock:
            self._block_reasons.pop(plugin_name, None)
    
    async def list_plugins(self) -> list[str]:
        """
        Получить список всех зарегистрированных плагинов.
        
        Returns:
            Список имён плагинов
        """
        async with self._plugin_lock:
            return list(self._plugins.keys())
    
    async def has_plugin(self, plugin_name: str) -> bool:
        """
        Проверить, зарегистрирован ли плагин.
        
        Args:
            plugin_name: имя плагина
            
        Returns:
            True если плагин зарегистрирован
        """
        async with self._plugin_lock:
            return plugin_name in self._plugins
    
    async def get_all_states(self) -> Dict[str, PluginState]:
        """
        Получить все состояния плагинов.
        
        Returns:
            Словарь {plugin_name: PluginState}
        """
        async with self._plugin_lock:
            return {name: PluginState(state_str) for name, state_str in self._states.items()}
    
    async def get_all_plugins(self) -> Dict[str, BasePlugin]:
        """
        Получить все зарегистрированные плагины.
        
        Returns:
            Словарь {plugin_name: plugin_instance}
        """
        async with self._plugin_lock:
            return dict(self._plugins)
