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
import importlib
import inspect
import pkgutil
from pathlib import Path

from core.event_bus import EventBus
from core.service_registry import ServiceRegistry
from core.state_engine import StateEngine
from core.storage import Storage
from core.plugin_manager import PluginManager
from core.http_registry import HttpRegistry


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
        self.plugin_manager = PluginManager(self)
        # Регистр HTTP-интерфейсов (каталог контрактов)
        self.http = HttpRegistry()
        
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
        
        # Если нет загруженных плагинов (например, в тестах с InMemoryStorageAdapter),
        # попытаться автозагрузить плагины из каталога plugins/
        if not self.plugin_manager.list_plugins():
            try:
                await self._auto_load_plugins()
            except Exception:
                # Не мешаем запуску runtime из-за проблем с автозагрузкой
                pass

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

    async def _auto_load_plugins(self) -> None:
        """
        Автоматически загрузить плагины из каталога `plugins/` рядом с корнем сервиса.

        Метод безопасен к повторным вызовам — ошибки загрузки отдельных плагинов
        игнорируются, а дублирующие загрузки не прерывают выполнение.
        """
        plugins_dir = Path(__file__).parent.parent / "plugins"
        if not plugins_dir.exists() or not plugins_dir.is_dir():
            return

        for _finder, mod_name, _ispkg in pkgutil.iter_modules([str(plugins_dir)]):
            module_name = f"plugins.{mod_name}"
            try:
                module = importlib.import_module(module_name)
                for _name, obj in inspect.getmembers(module, inspect.isclass):
                    try:
                        # Только подклассы BasePlugin
                        from plugins.base_plugin import BasePlugin

                        if issubclass(obj, BasePlugin) and obj is not BasePlugin:
                            try:
                                plugin_instance = obj(self)
                                await self.plugin_manager.load_plugin(plugin_instance)
                            except Exception:
                                # Игнорируем ошибки загрузки конкретного плагина
                                continue
                    except Exception:
                        continue
            except Exception:
                # Игнорируем ошибки при импорте модуля плагина
                continue
