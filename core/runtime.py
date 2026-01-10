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
from core.storage_mirror import StorageWithStateMirror
from core.plugin_manager import PluginManager
from core.module_manager import ModuleManager
from core.http_registry import HttpRegistry
from plugins import BasePlugin


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
        
        # Base storage adapter instance
        base_storage = Storage(storage_adapter)
        
        # Обёртка для синхронизации storage и state_engine
        self.storage = StorageWithStateMirror(base_storage, self.state_engine)
        self.plugin_manager = PluginManager(self)
        self.module_manager = ModuleManager()
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
        # попытаться автоматически загрузить плагины из каталога plugins/
        if not self.plugin_manager.list_plugins():
            try:
                await self._auto_load_plugins()
            except Exception as e:
                # Не мешаем запуску runtime из-за проблем с автозагрузкой
                # Логируем ошибку для отладки
                print(f"[Runtime] Предупреждение: ошибка автозагрузки плагинов: {e}", file=__import__('sys').stderr)

        # Регистрация встроенных модулей (обязательные домены)
        await self.module_manager.register_builtin_modules(self)
        
        # Логирование зарегистрированных модулей
        modules = self.module_manager.list_modules()
        if modules:
            print(f"[Runtime] Модули зарегистрированы: {modules}")

        # Запустить все модули (обязательные домены)
        await self.module_manager.start_all()
        if modules:
            print(f"[Runtime] Модули запущены: {modules}")
        
        # Запустить все плагины
        plugins = self.plugin_manager.list_plugins()
        await self.plugin_manager.start_all()
        if plugins:
            print(f"[Runtime] Плагины запущены: {plugins}")
        
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
        
        # Остановить все модули
        await self.module_manager.stop_all()
        
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
        
        # Очистить модули
        self.module_manager.clear()

        # Очистить компоненты
        await self.event_bus.clear()
        await self.service_registry.clear()
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

        for _finder, mod_name, _pkg in pkgutil.iter_modules([str(plugins_dir)]):
            module_name = f"plugins.{mod_name}"
            try:
                module = importlib.import_module(module_name)
            except Exception as e:
                # Игнорируем ошибки импорта отдельных модулей
                print(f"[Runtime] Предупреждение: не удалось импортировать модуль '{module_name}': {e}", file=__import__('sys').stderr)
                continue

            for _, obj in inspect.getmembers(module, inspect.isclass):
                if obj is BasePlugin:
                    continue

                try:
                    if not issubclass(obj, BasePlugin):
                        continue
                except TypeError:
                    # Не класс или не BasePlugin - пропускаем
                    continue

                try:
                    plugin_instance = obj(self)
                    await self.plugin_manager.load_plugin(plugin_instance)
                except Exception as e:
                    # Игнорируем ошибки загрузки отдельных плагинов
                    plugin_name = getattr(obj, '__name__', 'unknown')
                    print(f"[Runtime] Предупреждение: не удалось загрузить плагин '{plugin_name}': {e}", file=__import__('sys').stderr)
                    continue