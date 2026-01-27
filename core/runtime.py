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

from typing import Any, Dict, Optional
import asyncio
import time

from core.event_bus import EventBus
from core.service_registry import ServiceRegistry
from core.state_engine import StateEngine
from core.storage import Storage
from core.storage_mirror import StorageWithStateMirror
from core.plugin_manager import PluginManager, PluginState
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

    def __init__(self, storage_adapter: Any, config: Optional[Any] = None):
        """
        Инициализация Core Runtime.
        
        Args:
            storage_adapter: адаптер для работы с хранилищем
            config: опциональная конфигурация (для shutdown_timeout)
        """
        # Инициализация компонентов
        self.event_bus = EventBus()
        # ServiceRegistry с timeout из конфига (защита от зависших вызовов)
        default_timeout = config.service_call_timeout if config else None
        self.service_registry = ServiceRegistry(default_timeout=default_timeout)
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
        
        # Сохраняем config для shutdown_timeout
        self._config = config

        self._running = False
        self._start_time: Optional[float] = None

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
        
        Использует timeout из конфига (если доступен) для защиты от зависания.
        """
        if not self._running:
            return
        
        # Получаем timeout из конфига или используем значение по умолчанию
        timeout = 10
        if self._config is not None:
            timeout = getattr(self._config, "shutdown_timeout", 10)
        
        async def _stop_internal() -> None:
            """Внутренняя функция остановки."""
            # Остановить все плагины
            await self.plugin_manager.stop_all()
            
            # Остановить все модули
            await self.module_manager.stop_all()
            
            # Закрыть storage
            await self.storage.close()
            
            # Установить состояние runtime
            await self.state_engine.set("runtime.status", "stopped")
            self._running = False
        
        try:
            await asyncio.wait_for(_stop_internal(), timeout=timeout)
        except asyncio.TimeoutError:
            # Логируем timeout и принудительно завершаем
            try:
                await warning(
                    self,
                    f"Timeout ({timeout}s) при остановке runtime, принудительное завершение",
                    component="runtime"
                )
            except Exception:
                pass
            # Принудительно устанавливаем состояние остановки
            self._running = False
            raise

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
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Проверка здоровья всех компонентов runtime.
        
        Returns:
            Словарь с результатами проверки здоровья компонентов
        """
        from enum import Enum
        
        class HealthStatus(Enum):
            HEALTHY = "healthy"
            DEGRADED = "degraded"
            UNHEALTHY = "unhealthy"
        
        checks: Dict[str, str] = {}
        
        # Проверка Storage
        try:
            await self.storage.get("health_check", "test")
            checks["storage"] = HealthStatus.HEALTHY.value
        except Exception as e:
            checks["storage"] = HealthStatus.UNHEALTHY.value
            checks["storage_error"] = str(e)
        
        # Проверка модулей
        try:
            modules = self.module_manager.list_modules()
            required_modules = self.module_manager.get_required_modules()
            missing_required = [m for m in required_modules if m not in modules]
            if missing_required:
                checks["modules"] = HealthStatus.UNHEALTHY.value
                checks["modules_error"] = f"Missing required modules: {missing_required}"
            else:
                checks["modules"] = HealthStatus.HEALTHY.value
        except Exception as e:
            checks["modules"] = HealthStatus.UNHEALTHY.value
            checks["modules_error"] = str(e)
        
        # Проверка плагинов
        try:
            plugins = self.plugin_manager.list_plugins()
            error_plugins = [
                p for p in plugins
                if self.plugin_manager.get_plugin_state(p) == PluginState.ERROR
            ]
            if error_plugins:
                checks["plugins"] = HealthStatus.DEGRADED.value
                checks["plugins_error"] = f"Plugins in error state: {error_plugins}"
            else:
                checks["plugins"] = HealthStatus.HEALTHY.value
        except Exception as e:
            checks["plugins"] = HealthStatus.UNHEALTHY.value
            checks["plugins_error"] = str(e)
        
        # Определяем общий статус
        overall = HealthStatus.HEALTHY
        if any(c == HealthStatus.UNHEALTHY.value for c in checks.values()):
            overall = HealthStatus.UNHEALTHY
        elif any(c == HealthStatus.DEGRADED.value for c in checks.values()):
            overall = HealthStatus.DEGRADED
        
        return {
            "status": overall.value,
            "uptime": time.time() - self._start_time if self._start_time else 0,
            "checks": checks
        }
    
    async def get_metrics(self) -> Dict[str, Any]:
        """
        Получить метрики runtime.
        
        Returns:
            Словарь с метриками плагинов, модулей, сервисов и storage
        """
        metrics: Dict[str, Any] = {
            "uptime": time.time() - self._start_time if self._start_time else 0
        }
        
        # Метрики плагинов
        try:
            plugins = self.plugin_manager.list_plugins()
            plugin_states = {}
            for plugin_name in plugins:
                state = self.plugin_manager.get_plugin_state(plugin_name)
                if state:
                    plugin_states[plugin_name] = state.value
            
            started_count = sum(
                1 for state in plugin_states.values()
                if state == PluginState.STARTED.value
            )
            
            metrics["plugins"] = {
                "total": len(plugins),
                "started": started_count,
                "states": plugin_states
            }
        except Exception:
            metrics["plugins"] = {"error": "failed to collect"}
        
        # Метрики модулей
        try:
            modules = self.module_manager.list_modules()
            metrics["modules"] = {
                "total": len(modules),
                "list": modules
            }
        except Exception:
            metrics["modules"] = {"error": "failed to collect"}
        
        # Метрики сервисов
        try:
            services = await self.service_registry.list_services()
            metrics["services"] = {
                "total": len(services)
            }
        except Exception:
            metrics["services"] = {"error": "failed to collect"}
        
        # Метрики storage
        try:
            # Проверяем доступность storage
            await self.storage.get("metrics", "test")
            metrics["storage"] = {
                "available": True,
                "type": self.storage._adapter.__class__.__name__ if hasattr(self.storage, "_adapter") else "unknown"
            }
        except Exception as e:
            metrics["storage"] = {
                "available": False,
                "error": str(e)
            }
        
        # Метрики HTTP endpoints
        try:
            endpoints = self.http.list()
            metrics["http_endpoints"] = {
                "total": len(endpoints),
                "by_method": {}
            }
            for endpoint in endpoints:
                method = endpoint.method
                if method not in metrics["http_endpoints"]["by_method"]:
                    metrics["http_endpoints"]["by_method"][method] = 0
                metrics["http_endpoints"]["by_method"][method] += 1
        except Exception:
            metrics["http_endpoints"] = {"error": "failed to collect"}
        
        return metrics