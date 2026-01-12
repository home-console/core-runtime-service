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
from core.storage_mirror import StorageWithStateMirror
from core.plugin_manager import PluginManager
from core.module_manager import ModuleManager
from core.http_registry import HttpRegistry
from core.integration_registry import IntegrationRegistry
from core.logger_helper import info, warning
from core.base_plugin import BasePlugin



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
        self.module_manager = ModuleManager(self)
        # Регистр HTTP-интерфейсов (каталог контрактов)
        self.http = HttpRegistry()
        # Реестр интеграций (минимальный каталог для admin API)
        self.integrations = IntegrationRegistry()

        self._running = False

    @property
    def is_running(self) -> bool:
        """Запущен ли runtime."""
        return self._running

    async def start(self) -> None:
        """
        Запустить Core Runtime.
        
        Runtime НЕ стартует, если хоть один REQUIRED RuntimeModule:
        - не зарегистрировался
        - не смог выполниться register()
        - упал в start()
        
        Гарантии:
        - Все REQUIRED модули должны быть зарегистрированы и запущены
        - При ошибке старта REQUIRED модуля runtime останавливается
        - stop_all() вызывается даже при частичном старте
        
        Raises:
            RuntimeError: если REQUIRED модуль не зарегистрирован или не запустился
        """
        if self._running:
            return
        
        try:
            # Если нет загруженных плагинов (например, в тестах с InMemoryStorageAdapter),
            # попытаться автоматически загрузить плагины из каталога plugins/
            if not self.plugin_manager.list_plugins():
                try:
                    await self.plugin_manager.auto_load_plugins()
                except Exception as e:
                    # Не мешаем запуску runtime из-за проблем с автозагрузкой
                    # Логируем ошибку для отладки
                    await warning(self, f"Ошибка автозагрузки плагинов: {e}", component="runtime")

            # Регистрация встроенных модулей (обязательные домены)
            # register_builtin_modules() выбросит RuntimeError если REQUIRED модуль не зарегистрировался
            await self.module_manager.register_builtin_modules(self)
            
            # Проверка, что все REQUIRED модули зарегистрированы
            # Это дополнительная проверка на случай, если register_builtin_modules() не выбросил ошибку
            self.module_manager.check_required_modules_registered()
            
            # Логирование зарегистрированных модулей
            modules = self.module_manager.list_modules()
            if modules:
                await info(self, f"Модули зарегистрированы: {modules}", component="runtime")

            # Запустить все модули (обязательные домены)
            # start_all() выбросит RuntimeError если REQUIRED модуль упал в start()
            await self.module_manager.start_all()
            if modules:
                await info(self, f"Модули запущены: {modules}", component="runtime")
            
            # Запустить все плагины
            plugins = self.plugin_manager.list_plugins()
            await self.plugin_manager.start_all()
            if plugins:
                await info(self, f"Плагины запущены: {plugins}", component="runtime")
            
            # Установить состояние runtime
            await self.state_engine.set("runtime.status", "running")
            self._running = True
            
        except Exception as e:
            # При любой ошибке старта останавливаем все модули
            # Гарантия: stop_all вызывается даже при частичном старте
            try:
                await self.module_manager.stop_all()
            except Exception as stop_error:
                # Логируем ошибку остановки, но не маскируем исходную ошибку
                await warning(self, f"Ошибка при остановке модулей после ошибки старта: {stop_error}", component="runtime")
            
            # Пробрасываем исходную ошибку
            raise

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
