"""
CoreRuntime - главный класс Core Runtime (D1).

Объединяет все компоненты:
- EventBus
- ServiceRegistry
- StateEngine
- Storage
- PluginManager

Это kernel/runtime, а не backend-приложение.

Методы:
- Инициализация (init, _build_default_orchestration_service)
- Жизненный цикл (start, stop, shutdown, run) -> delegated to runtime.lifecycle
- Мониторинг (health_check, get_metrics) -> delegated to runtime.monitoring
- Транспорт (run_transports, iter_transport_runners)
"""

from typing import Any, Dict, Optional, Awaitable, Callable, cast
import asyncio
import os
import time

from core.event_bus import EventBus
from core.service import ServiceRegistry
from core.state_engine import StateEngine
from core.kernel.plugin_manager import PluginManager
from core.kernel.plugin_registry import PluginState
from core.module import ModuleManager
from core.http import HttpRegistry
from core.integration_registry import IntegrationRegistry
from core.capability import CapabilityRegistry
from core.logger_helper import info, warning
from core.base_plugin import BasePlugin
from core.operations.manager import OperationManager
from core.dependency import DependencyResolver, RuntimeIntegrityError  # Step 10
from core.policy import PolicyEngine
from core.runtime_context import RuntimeContext
from core.runtime_interface import IRuntimeModule, IPluginRegistry
from core.orchestration import (
    OrchestrationService,
    DockerOrchestrationBackend,
    NullOrchestrationBackend,
)

# Import extracted lifecycle and monitoring functions
from core.runtime.lifecycle import start_runtime, stop_runtime, shutdown_runtime, hydrate_critical_state
from core.runtime.monitoring import health_check as _health_check, get_metrics as _get_metrics


class CoreRuntime:
    """
    Главный класс Core Runtime.
    
    Координирует работу всех компонентов.
    Предоставляет единую точку доступа для плагинов.
    """

    def __init__(
        self,
        storage_port: Any,
        config: Optional[Any] = None,
        vault_port: Optional[Any] = None,
        state_engine: Optional[Any] = None,
        *,
        policy_engine: Optional[PolicyEngine] = None,
        orchestration_service: Optional[OrchestrationService] = None,
    ):
        """
        Инициализация Core Runtime.
        
        Args:
            storage_port: CoreStoragePort для доступа к core storage
            config: опциональная конфигурация (для shutdown_timeout)
            vault_port: опциональный VaultStoragePort для доступа к vault (если dual-mode)
            state_engine: опциональный StateEngine (если None, создаётся новый)
        """
        # Сохраняем config заранее, чтобы остальные компоненты могли читать extensibility-настройки.
        self._config = config
        self.config = config

        # Инициализация компонентов
        self.event_bus = EventBus()
        # PolicyEngine — per-runtime dependency, без обязательного глобального singleton.
        self.policy_engine = policy_engine or PolicyEngine()

        # ServiceRegistry с timeout из конфига (защита от зависших вызовов)
        default_timeout = config.service_call_timeout if config else None
        self.service_registry = ServiceRegistry(default_timeout=default_timeout, policy_engine=self.policy_engine)
        
        # StateEngine (используем переданный или создаём новый)
        self.state_engine = state_engine if state_engine is not None else StateEngine()
        
        # Storage port для core storage (уже обёрнут в StorageWithStateMirror)
        self.storage = storage_port.storage
        
        # Vault port для vault storage (если dual-mode)
        self.vault = vault_port if vault_port else None
        # Регистр HTTP-интерфейсов (каталог контрактов)
        self.http = HttpRegistry()
        # Реестр интеграций (минимальный каталог для admin API)
        self.integrations = IntegrationRegistry()
        # Реестр capability (только метаданные: provider/consumer, проверки, диагностика)
        self.capability_registry = CapabilityRegistry()
        # Operations manager (инфраструктура для всех модулей)
        self.operations = OperationManager(self)
        self.plugin_manager = PluginManager(self)
        module_path_prefix = getattr(config, "module_path_prefix", "modules") if config is not None else "modules"
        self.module_manager = ModuleManager(self, module_path_prefix=module_path_prefix)
        # Dependency resolver для проверки integrity (не знает про HTTP/marketplace)
        self.dependency_resolver = DependencyResolver(
            self.capability_registry,
            self.plugin_manager,
            self.storage
        )
        
        # Step 15: Agent Control Plane components
        # Will be initialized in start() when SecretStore is ready
        self.agent_manager: Optional[Any] = None
        self.agent_registry: Optional[Any] = None
        self.deployment_tracker: Optional[Any] = None  # DeploymentTracker instance
        self.mtls_ca: Optional[Any] = None
        # SecretStore (vault) — выставляется в main; используется credentials и inspector в debug
        self.secret_store: Optional[Any] = None
        # StorageManager (core + vault) — выставляется в main для модуля credentials
        self.storage_manager: Optional[Any] = None
        
        self._running = False
        self._start_time: Optional[float] = None

        # Execution controller (опционально; выставляется модулем execution)
        self.execution_controller: Optional[Any] = None
        
        # OrchestrationService — DI зависимость, configurable backend.
        self.orchestration_service = orchestration_service or self._build_default_orchestration_service()

    def _build_default_orchestration_service(self) -> OrchestrationService:
        """Собрать orchestration service из runtime config без глобального singleton."""
        backend_name = getattr(self._config, "orchestration_backend", "docker") if self._config is not None else "docker"
        if backend_name == "none":
            return OrchestrationService(NullOrchestrationBackend())
        return OrchestrationService(DockerOrchestrationBackend())

    def _iter_transport_runners(self) -> list[tuple[str, Callable[[Any], Awaitable[Any]]]]:
        """
        Найти transport runner'ы среди зарегистрированных модулей.

        Новый контракт: модуль может экспортировать `run_transport(runtime)`.
        Backward-compat: если его нет, используем legacy `run_http(runtime)`.
        """
        runners: list[tuple[str, Callable[[Any], Awaitable[Any]]]] = []
        for module_name in self.module_manager.list_modules():
            module = self.module_manager.get_module(module_name)
            if module is None:
                continue

            run_transport = getattr(module, "run_transport", None)
            if callable(run_transport):
                runners.append((module_name, cast(Callable[[Any], Awaitable[Any]], run_transport)))
                continue

            run_http = getattr(module, "run_http", None)
            if callable(run_http):
                runners.append((module_name, cast(Callable[[Any], Awaitable[Any]], run_http)))
        return runners

    async def _run_transports(self) -> None:
        """Запустить transport runner'ы модулей."""
        runners = self._iter_transport_runners()
        if not runners:
            await info(self, "RUNTIME: no transport runners registered", component="runtime")
            return

        for module_name, runner in runners:
            try:
                await info(self, f"RUNTIME: running transport for module '{module_name}'", component="runtime")
                await runner(self)
                await info(self, f"RUNTIME: transport runner for '{module_name}' returned", component="runtime")
            except Exception as e:
                await warning(self, f"Ошибка transport runner '{module_name}': {e}", component="runtime")
                import traceback
                traceback.print_exc()
    
    async def run(self) -> None:
        """
        Верный запуск: start (модули + плагины), затем transport runner'ы модулей.
        Backward-compat: legacy `run_http(runtime)` тоже поддерживается.
        """
        await info(self, "RUNTIME: start() about to run", component="runtime")
        await self.start()
        await info(self, "RUNTIME: start() finished", component="runtime")

        await self._run_transports()
        try:
            timeout = getattr(self._config, "shutdown_timeout", 10) if self._config else 10
            await asyncio.wait_for(self.shutdown(), timeout=timeout)
        except asyncio.TimeoutError:
            await warning(self, "Таймаут при остановке", component="runtime")
    
    def create_context(self) -> RuntimeContext:
        """
        Создать RuntimeContext для модулей и плагинов.
        
        Возвращает ограниченный контекст с только необходимыми компонентами.
        Используется модулями и плагинами вместо прямого доступа к runtime.
        
        Returns:
            RuntimeContext с storage, services, http, capabilities, operations
        """
        return RuntimeContext(
            storage=self.storage,
            vault=self.vault,
            services=self.service_registry,
            http=self.http,
            capabilities=self.capability_registry,
            operations=self.operations,
            state=self.state_engine,
        )

    @property
    def state(self):
        """Алиас для state_engine. Плагины и Inspector используют runtime.state.get/set."""
        return self.state_engine

    @property
    def is_running(self) -> bool:
        """Запущен ли runtime."""
        return self._running
    
    async def _hydrate_critical_state(self) -> None:
        """
        Гидратировать критичные данные из persistent storage в StateEngine.
        Делегирует к runtime.lifecycle.hydrate_critical_state()
        """
        await hydrate_critical_state(self)

    async def start(self) -> None:
        """
        Запустить Core Runtime.
        Делегирует к runtime.lifecycle.start_runtime()
        """
        await start_runtime(self)

    async def stop(self) -> None:
        """
        Остановить Core Runtime.
        Делегирует к runtime.lifecycle.stop_runtime()
        """
        await stop_runtime(self)

    async def shutdown(self) -> None:
        """
        Полное завершение работы Runtime.
        Делегирует к runtime.lifecycle.shutdown_runtime()
        """
        await shutdown_runtime(self)
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Проверка здоровья всех компонентов runtime.
        Делегирует к runtime.monitoring.health_check()
        """
        return await _health_check(self)
    
    async def get_metrics(self) -> Dict[str, Any]:
        """
        Получить метрики runtime.
        Делегирует к runtime.monitoring.get_metrics()
        """
        return await _get_metrics(self)
