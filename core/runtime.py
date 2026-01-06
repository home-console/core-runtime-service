"""
CoreRuntime - главный класс Core Runtime.

Объединяет все компоненты:
- EventBus
- ServiceRegistry
- StateEngine
- Storage
- PluginManager

Это kernel/runtime, а не backend-приложение.
"""

from typing import Any

from core.event_bus import EventBus
from core.service_registry import ServiceRegistry
from core.state_engine import StateEngine
from core.storage import Storage
from core.plugin_manager import PluginManager


class CoreRuntime:
    """
    Главный класс Core Runtime.
    
    Координирует работу всех компонентов.
    Предоставляет единую точку доступа для плагинов.
    """

    def __init__(self, storage_adapter: Any):
        """
        Инициализация Core Runtime.
        
        Args:
            storage_adapter: адаптер для работы с хранилищем
        """
        # Инициализация компонентов
        self.event_bus = EventBus()
        self.service_registry = ServiceRegistry()
        self.state_engine = StateEngine()
        self.storage = Storage(storage_adapter)
        self.plugin_manager = PluginManager()
        
        self._running = False

    @property
    def is_running(self) -> bool:
        """Запущен ли runtime."""
        return self._running

    async def start(self) -> None:
        """
        Запустить Core Runtime.
        
        - запускает все загруженные плагины
        - устанавливает флаг running
        """
        if self._running:
            return
        
        # Запустить все плагины
        await self.plugin_manager.start_all()
        
        # Установить состояние runtime
        await self.state_engine.set("runtime.status", "running")
        self._running = True

    async def stop(self) -> None:
        """
        Остановить Core Runtime.
        
        - останавливает все плагины
        - очищает состояние
        - закрывает storage
        """
        if not self._running:
            return
        
        # Остановить все плагины
        await self.plugin_manager.stop_all()
        
        # Закрыть storage
        await self.storage.close()
        
        # Установить состояние runtime
        await self.state_engine.set("runtime.status", "stopped")
        self._running = False

    async def shutdown(self) -> None:
        """
        Полное завершение работы Runtime.
        
        - останавливает runtime
        - очищает все компоненты
        """
        await self.stop()
        
        # Очистить компоненты
        self.event_bus.clear()
        self.service_registry.clear()
        await self.state_engine.clear()
