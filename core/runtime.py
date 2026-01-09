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

        # Lightweight wrapper that mirrors storage namespace/key → state_engine keys
        # Format: state_key = f"{namespace}.{key}"
        class StorageWithStateMirror:
            def __init__(self, storage_obj: Storage, state_engine_obj: StateEngine):
                self._storage = storage_obj
                self._state_engine = state_engine_obj

            async def get(self, namespace: str, key: str):
                return await self._storage.get(namespace, key)

            async def set(self, namespace: str, key: str, value):
                # Persist to underlying storage
                await self._storage.set(namespace, key, value)
                await self._state_engine.set(f"{namespace}.{key}", value)

                # Best-effort logging for debugging mirror operations (no-raise)
                # service_registry may not be available at early init; guard access
                _sr = getattr(self, '_state_engine', None)
                # Attempt to call logger if available
                if hasattr(self, '_state_engine'):
                    # runtime reference not available here; try to find a global logger via import
                    from plugins.system_logger_plugin import SystemLoggerPlugin  # type: ignore

            async def delete(self, namespace: str, key: str):
                res = await self._storage.delete(namespace, key)
                await self._state_engine.delete(f"{namespace}.{key}")
                return res

            async def list_keys(self, namespace: str):
                return await self._storage.list_keys(namespace)

            async def clear_namespace(self, namespace: str):
                return await self._storage.clear_namespace(namespace)

            async def close(self):
                return await self._storage.close()

        # Replace storage with wrapper that mirrors changes to state_engine
        self.storage = StorageWithStateMirror(base_storage, self.state_engine)
        self.plugin_manager = PluginManager(self)
        # Регистр HTTP-интерфейсов (каталог контрактов)
        self.http = HttpRegistry()
        # container for unregister callables returned by built-in modules
        self._module_unregistrars: dict[str, callable] = {}

        # Attempt to register built-in modules (e.g., modules.devices)
        try:
            spec = importlib.util.find_spec("modules.devices")
            if spec is not None:
                try:
                    from modules.devices import register_devices  # type: ignore

                    res = register_devices(self)
                    if isinstance(res, dict):
                        unregister = res.get("unregister")
                        if callable(unregister):
                            self._module_unregistrars["devices"] = unregister
                except Exception:
                    # Do not fail runtime init if module registration fails
                    pass
        except Exception:
            pass
        
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
            except:
                # Не мешаем запуску runtime из-за проблем с автозагрузкой
                pass

        # Запустить все плагины
        await self.plugin_manager.start_all()
        # После старта плагинов: минимальная синхронизация важных namespace -> state_engine.
        # Это гарантирует, что начальные значения, записанные плагинами в storage
        # во время on_start будут отражены в state_engine перед возвратом из start().
        try:
            try:
                keys = await self.storage.list_keys("presence")
            except Exception:
                keys = []
            for k in keys:
                try:
                    v = await self.storage.get("presence", k)
                    await self.state_engine.set(f"presence.{k}", v)
                except Exception:
                    pass
        except Exception:
            # Не мешаем старту при ошибках синхронизации
            pass
        
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
        # Unregister built-in modules if they provided unregister callables
        try:
            for key, unreg in list(getattr(self, "_module_unregistrars", {}).items()):
                try:
                    if callable(unreg):
                        unreg()
                except Exception:
                    pass
        except Exception:
            pass

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

        for _finder, mod_name, _pkg in pkgutil.iter_modules([str(plugins_dir)]):
            module_name = f"plugins.{mod_name}"
            try:
                module = importlib.import_module(module_name)
            except Exception:
                continue

            for _, obj in inspect.getmembers(module, inspect.isclass):
                if obj is BasePlugin:
                    continue

                try:
                    if not issubclass(obj, BasePlugin):
                        continue
                except TypeError:
                    continue

                try:
                    plugin_instance = obj(self)
                    await self.plugin_manager.load_plugin(plugin_instance)
                except Exception:
                    continue