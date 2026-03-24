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

import asyncio
import time
from typing import Any, Awaitable, Callable, Dict, Optional, cast

from modules.capability.registry import CapabilityRegistry
from modules.event_bus.inmemory import InMemoryEventBus
from modules.policy.engine import PolicyEngine

from core.dependency_resolver import (  # Step 10
    DependencyResolver,
    RuntimeIntegrityError,
)
from core.http import HttpRegistry
from core.kernel.context import KernelContext
from core.kernel.plugin_manager import PluginManager
from core.logger_helper import info, warning
from core.operations.manager import OperationManager
from core.operations.worker import OperationWorker
from core.orchestration import (
    DockerOrchestrationBackend,
    NullOrchestrationBackend,
    OrchestrationService,
)
from core.plugins import PluginState
from core.runtime.module_manager import ModuleManager
from core.runtime.runtime_context import RuntimeContext
from core.service import ServiceRegistry
from core.state_engine import StateEngine
from modules.integrations.registry import IntegrationRegistry


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
        self.event_bus = InMemoryEventBus(storage=storage_port.storage)
        # PolicyEngine — per-runtime dependency, без обязательного глобального singleton.
        self.policy_engine = policy_engine or PolicyEngine()

        # ServiceRegistry с timeout из конфига (защита от зависших вызовов)
        default_timeout = config.service_call_timeout if config else None
        self.service_registry = ServiceRegistry(default_timeout=default_timeout)

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
        # TODO: remove modules.plugins.manager shim (backward compat)
        self.plugin_manager = PluginManager(self)
        module_path_prefix = (
            getattr(config, "module_path_prefix", "modules")
            if config is not None
            else "modules"
        )
        self.module_manager = ModuleManager(self, module_path_prefix=module_path_prefix)
        # Dependency resolver для проверки integrity (не знает про HTTP/marketplace)
        self.dependency_resolver = DependencyResolver(
            self.capability_registry, self.plugin_manager, self.storage
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
        # Optional app-level middleware factory. Core keeps no direct module dependency.
        self.event_validation_middleware_factory: Optional[Callable[[], Any]] = None
        # Optional app-level plugin isolation wiring. Core keeps no direct module dependency.
        self.plugin_storage_proxy_cls: Optional[type] = None
        self.plugin_service_proxy_cls: Optional[type] = None
        self.plugin_default_allowed_services: list[str] = []

        # Сохраняем config для shutdown_timeout
        self._config = config

        self.kernel_context: Optional[KernelContext] = KernelContext(
            {"service_registry": self.service_registry},
            self.state_engine,
            event_bus=self.event_bus,
        )

        self._running = False
        self._start_time: Optional[float] = None

        # Execution controller (опционально; выставляется модулем execution)
        self.execution_controller: Optional[Any] = None
        self.worker: Optional[OperationWorker] = None
        self._worker_task: Optional[asyncio.Task] = None

        # OrchestrationService — DI зависимость, configurable backend.
        self.orchestration_service = (
            orchestration_service or self._build_default_orchestration_service()
        )

    def _build_default_orchestration_service(self) -> OrchestrationService:
        """Собрать orchestration service из runtime config без глобального singleton."""
        backend_name = (
            getattr(self._config, "orchestration_backend", "docker")
            if self._config is not None
            else "docker"
        )
        if backend_name == "none":
            return OrchestrationService(NullOrchestrationBackend())
        return OrchestrationService(DockerOrchestrationBackend())

    def _iter_transport_runners(
        self,
    ) -> list[tuple[str, Callable[[Any], Awaitable[Any]]]]:
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
                runners.append(
                    (module_name, cast(Callable[[Any], Awaitable[Any]], run_transport))
                )
                continue

            run_http = getattr(module, "run_http", None)
            if callable(run_http):
                runners.append(
                    (module_name, cast(Callable[[Any], Awaitable[Any]], run_http))
                )
        return runners

    async def _run_transports(self) -> None:
        """Запустить transport runner'ы модулей."""
        runners = self._iter_transport_runners()
        if not runners:
            await info(
                self, "RUNTIME: no transport runners registered", component="runtime"
            )
            return

        for module_name, runner in runners:
            try:
                await info(
                    self,
                    f"RUNTIME: running transport for module '{module_name}'",
                    component="runtime",
                )
                await runner(self)
                await info(
                    self,
                    f"RUNTIME: transport runner for '{module_name}' returned",
                    component="runtime",
                )
            except Exception as e:
                await warning(
                    self,
                    f"Ошибка transport runner '{module_name}': {e}",
                    component="runtime",
                )
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

        await info(self, "RUNTIME: about to run HTTP", component="runtime")
        api_module = self.module_manager.get_module("api")
        run_http = (
            getattr(api_module, "run_http", None) if api_module is not None else None
        )
        if callable(run_http):
            try:
                run_http_fn = cast(Callable[[Any], Awaitable[Any]], run_http)
                await run_http_fn(self)
                await info(self, "RUNTIME: run_http returned", component="runtime")
            except Exception as e:
                await warning(self, f"Ошибка HTTP: {e}", component="runtime")
                import traceback

                traceback.print_exc()
        else:
            await info(
                self, "RUNTIME: api_module missing or no run_http", component="runtime"
            )
        try:
            timeout = (
                getattr(self._config, "shutdown_timeout", 10) if self._config else 10
            )
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
        # TODO: migrate to KernelContext
        self.kernel_context = KernelContext(
            {"service_registry": self.service_registry},
            self.state_engine,
            event_bus=self.event_bus,
        )
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

        Восстанавливает данные для быстрого доступа при старте без полной загрузки
        всех данных в память. Критичные namespaces:
        - plugins.* : метаданные плагинов
        - agent.* : идентификационные данные агентов
        - ca.* : CA сертификаты

        Эта операция выполняется ПЕРЕД запуском модулей, чтобы модули
        могли сразу использовать восстановленное состояние.
        """
        critical_prefixes = ["plugins.", "agent.", "ca.", "runtime.snapshots"]

        try:
            # Загружаем все namespaces, которые начинаются с критичных префиксов
            all_namespaces = await self.storage.list_namespaces()

            for namespace in all_namespaces:
                # Проверяем, является ли namespace критичным
                is_critical = any(
                    namespace.startswith(prefix) for prefix in critical_prefixes
                )

                if is_critical:
                    # Итерируем по ключам в namespace и загружаем в StateEngine
                    hydrated_count = 0
                    try:
                        async for key, value in self.storage.iter_namespace(namespace):
                            state_key = f"{namespace}.{key}"
                            await self.state_engine.set(state_key, value)
                            hydrated_count += 1
                    except Exception as e:
                        # Логируем ошибку, но не останавливаем гидратацию
                        await warning(
                            self,
                            f"Ошибка при гидратации namespace '{namespace}': {e}",
                            component="runtime",
                        )

                    if hydrated_count > 0:
                        await info(
                            self,
                            f"Гидратирован namespace '{namespace}' ({hydrated_count} ключей)",
                            component="runtime",
                        )
        except Exception as e:
            # Гидратация - опциональная оптимизация, ошибка не должна блокировать старт
            await warning(
                self,
                f"Ошибка гидратации critical state: {e}. Система продолжит работу, но может быть медленнее.",
                component="runtime",
            )

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

        import os

        debug_mode = os.getenv("DEBUG_MODE", "true").lower() != "false"

        try:
            # DEBUG KERNEL: Log kernel startup
            if debug_mode:
                await info(
                    self,
                    "🔧 KERNEL DEBUG: Starting Core Runtime bootstrap",
                    component="runtime",
                )

            middleware_names = await self.event_bus.list_middleware()
            middleware_factory = self.event_validation_middleware_factory
            if callable(middleware_factory):
                middleware = middleware_factory()
                middleware_name = type(middleware).__name__
                if middleware_name not in middleware_names:
                    await self.event_bus.add_middleware(middleware)

            # Модули регистрируются приложением (bootstrap) через register_module_specs() до вызова start().
            # Проверка, что все REQUIRED модули зарегистрированы (список required задаётся приложением)
            self.module_manager.check_required_modules_registered()

            # Логирование зарегистрированных модулей
            modules = self.module_manager.list_modules()
            if modules:
                await info(
                    self, f"Модули зарегистрированы: {modules}", component="runtime"
                )
                if debug_mode:
                    await info(
                        self,
                        f"🔧 KERNEL DEBUG: Registered {len(modules)} modules",
                        component="runtime",
                    )

            # P0: Hydrate critical state from persistent storage
            # Восстанавливаем критичные данные из storage в StateEngine для быстрого доступа
            # (plugins metadata, agent identities, CA certificate)
            if debug_mode:
                await info(
                    self,
                    "🔧 KERNEL DEBUG: Hydrating critical state from storage",
                    component="runtime",
                )
            await self._hydrate_critical_state()

            # Запустить все модули (обязательные домены)
            # start_all() выбросит RuntimeError если REQUIRED модуль упал в start()
            if debug_mode:
                await info(
                    self,
                    f"🔧 KERNEL DEBUG: Starting {len(modules)} modules",
                    component="runtime",
                )
            await self.module_manager.start_all()
            if modules:
                await info(self, f"Модули запущены: {modules}", component="runtime")
                if debug_mode:
                    await info(
                        self,
                        f"🔧 KERNEL DEBUG: All {len(modules)} modules started successfully",
                        component="runtime",
                    )

            # P0: Автозагрузка плагинов из папки plugins/ (один раз после модулей)
            # Сканируем папку, в каждой подпапке ищем manifest/plugin.json — если валидный, грузим плагин
            plugins = await self.plugin_manager.list_plugins()
            if not plugins and not os.getenv("TEST_MODE"):
                try:
                    if debug_mode:
                        await info(
                            self,
                            "🔧 KERNEL DEBUG: Auto-loading plugins from plugins/ directory",
                            component="runtime",
                        )
                    await self.plugin_manager.auto_load_plugins()
                except Exception as e:
                    await warning(
                        self, f"Ошибка автозагрузки плагинов: {e}", component="runtime"
                    )

            # Запустить все плагины
            plugins = await self.plugin_manager.list_plugins()
            if debug_mode:
                await info(
                    self,
                    f"🔧 KERNEL DEBUG: Starting {len(plugins)} plugins",
                    component="runtime",
                )
            await info(
                self,
                "RUNTIME: about to call plugin_manager.start_all()",
                component="runtime",
            )
            await self.plugin_manager.start_all()
            await info(
                self,
                "RUNTIME: plugin_manager.start_all() returned",
                component="runtime",
            )

            # Логируем как список, так и сводку по количеству и состояниям
            if plugins:
                await info(self, f"Плагины запущены: {plugins}", component="runtime")

            # Сводка: сколько реально запущено / заблокировано / с ошибкой
            if plugins:
                started = []
                blocked = []
                error = []
                for name in plugins:
                    state = await self.plugin_manager.get_plugin_state(name)
                    if state == PluginState.STARTED:
                        started.append(name)
                    elif state == PluginState.ERROR:
                        error.append(name)
                    else:
                        # LOADED, STOPPED и т.п. считаем "не стартовали до конца"
                        # В отдельную категорию "заблокировано" относим те, у кого есть block_reason
                        if await self.plugin_manager.get_plugin_block_reason(name):
                            blocked.append(name)
                await info(
                    self,
                    (
                        "Сводка плагинов: "
                        f"всего={len(plugins)}, "
                        f"запущено={len(started)}, "
                        f"заблокировано={len(blocked)}, "
                        f"с ошибкой={len(error)}"
                    ),
                    component="runtime",
                )
                if debug_mode:
                    await info(
                        self,
                        f"🔧 KERNEL DEBUG: Plugins started={len(started)} blocked={len(blocked)} error={len(error)}",
                        component="runtime",
                    )
            # Also print plugin list to stdout for quick visibility in console
            try:
                if plugins:
                    print("[Runtime] Плагины:")
                    for name in plugins:
                        state = await self.plugin_manager.get_plugin_state(name)
                        block = await self.plugin_manager.get_plugin_block_reason(name)
                        state_str = state.value if state is not None else "unknown"
                        if block:
                            print(f"  - {name}: {state_str} (blocked: {block})")
                        else:
                            print(f"  - {name}: {state_str}")
            except Exception:
                pass

            # Проверить что система в консистентном состоянии (все dependencies удовлетворены)
            integrity_errors = self.dependency_resolver.validate_runtime_integrity()
            if integrity_errors:
                raise RuntimeIntegrityError(integrity_errors)

            # Установить состояние runtime
            await self.state_engine.set("runtime.status", "running")
            self._running = True
            self._start_time = time.time()

            if self.worker is None:
                self.worker = OperationWorker(self)
            if self._worker_task is None or self._worker_task.done():
                self._worker_task = asyncio.create_task(self.worker.start())
                self.worker._task = self._worker_task

            # DEBUG KERNEL: Log successful startup
            if debug_mode:
                uptime_ms = int((time.time() - self._start_time) * 1000)
                await info(
                    self,
                    f"✅ KERNEL DEBUG: Core Runtime started successfully in {uptime_ms}ms",
                    component="runtime",
                )

        except Exception as e:
            # При любой ошибке старта останавливаем все модули
            # Гарантия: stop_all вызывается даже при частичном старте
            if debug_mode:
                await warning(
                    self,
                    f"❌ KERNEL DEBUG: Core Runtime startup failed: {type(e).__name__}: {str(e)}",
                    component="runtime",
                )

            try:
                await self.module_manager.stop_all()
            except Exception as stop_error:
                # Логируем ошибку остановки, но не маскируем исходную ошибку
                await warning(
                    self,
                    f"Ошибка при остановке модулей после ошибки старта: {stop_error}",
                    component="runtime",
                )

            # Пробрасываем исходную ошибку
            raise

    async def stop(self) -> None:
        """
        Остановить Core Runtime.

        - сигналит HTTP серверу (should_exit)
        - останавливает все плагины
        - очищает состояние
        - закрывает storage

        Использует timeout из конфига (если доступен) для защиты от зависания.
        """
        if not self._running:
            return

        import os

        debug_mode = os.getenv("DEBUG_MODE", "true").lower() != "false"

        if debug_mode:
            await info(
                self, "🔧 KERNEL DEBUG: Stopping Core Runtime", component="runtime"
            )

        # Получаем timeout из конфига или используем значение по умолчанию
        timeout = 10
        if self._config is not None:
            timeout = getattr(self._config, "shutdown_timeout", 10)

        async def _stop_internal() -> None:
            """Внутренняя функция остановки."""
            if self.worker is not None:
                await self.worker.stop()

            if debug_mode:
                await info(
                    self, "🔧 KERNEL DEBUG: Stopping all plugins", component="runtime"
                )
            # Остановить все плагины
            await self.plugin_manager.stop_all()

            if debug_mode:
                await info(
                    self, "🔧 KERNEL DEBUG: Stopping all modules", component="runtime"
                )
            # Остановить все модули
            await self.module_manager.stop_all()

            if debug_mode:
                await info(
                    self, "🔧 KERNEL DEBUG: Closing storage", component="runtime"
                )
            # Закрыть storage
            await self.storage.close()

            # Установить состояние runtime
            await self.state_engine.set("runtime.status", "stopped")
            self._running = False
            self._worker_task = None

            if debug_mode:
                await info(
                    self,
                    "✅ KERNEL DEBUG: Core Runtime stopped successfully",
                    component="runtime",
                )

        try:
            await asyncio.wait_for(_stop_internal(), timeout=timeout)
        except asyncio.TimeoutError:
            # Логируем timeout и принудительно завершаем
            try:
                await warning(
                    self,
                    f"Timeout ({timeout}s) при остановке runtime, принудительное завершение",
                    component="runtime",
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
        import os

        debug_mode = os.getenv("DEBUG_MODE", "true").lower() != "false"

        if debug_mode:
            await info(
                self, "🔧 KERNEL DEBUG: Initiating full shutdown", component="runtime"
            )

        await self.stop()

        if debug_mode:
            await info(self, "🔧 KERNEL DEBUG: Clearing modules", component="runtime")
        # Очистить модули
        self.module_manager.clear()

        if debug_mode:
            await info(
                self,
                "🔧 KERNEL DEBUG: Clearing event bus, services, state",
                component="runtime",
            )
        # Очистить компоненты
        await self.event_bus.clear()
        await self.service_registry.clear()
        await self.state_engine.clear()

        if debug_mode:
            await info(
                self, "✅ KERNEL DEBUG: Full shutdown complete", component="runtime"
            )

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
                checks["modules_error"] = (
                    f"Missing required modules: {missing_required}"
                )
            else:
                checks["modules"] = HealthStatus.HEALTHY.value
        except Exception as e:
            checks["modules"] = HealthStatus.UNHEALTHY.value
            checks["modules_error"] = str(e)

        # Проверка плагинов
        try:
            plugins = self.plugin_manager.list_plugins()
            error_plugins = [
                p
                for p in plugins
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
            "checks": checks,
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
            plugins = await self.plugin_manager.list_plugins()
            plugin_states = {}
            for plugin_name in plugins:
                state = await self.plugin_manager.get_plugin_state(plugin_name)
                if state:
                    plugin_states[plugin_name] = state.value

            started_count = sum(
                1
                for state in plugin_states.values()
                if state == PluginState.STARTED.value
            )

            metrics["plugins"] = {
                "total": len(plugins),
                "started": started_count,
                "states": plugin_states,
            }
        except Exception:
            metrics["plugins"] = {"error": "failed to collect"}

        # Метрики модулей
        try:
            modules = self.module_manager.list_modules()
            metrics["modules"] = {"total": len(modules), "list": modules}
        except Exception:
            metrics["modules"] = {"error": "failed to collect"}

        # Метрики сервисов
        try:
            services = await self.service_registry.list_services()
            metrics["services"] = {"total": len(services)}
        except Exception:
            metrics["services"] = {"error": "failed to collect"}

        # Метрики storage
        try:
            # Проверяем доступность storage
            await self.storage.get("metrics", "test")
            metrics["storage"] = {
                "available": True,
                "type": self.storage.get_backend_name(),
            }
        except Exception as e:
            metrics["storage"] = {"available": False, "error": str(e)}

        # Метрики HTTP endpoints
        try:
            endpoints = self.http.list()
            metrics["http_endpoints"] = {"total": len(endpoints), "by_method": {}}
            for endpoint in endpoints:
                method = endpoint.method
                if method not in metrics["http_endpoints"]["by_method"]:
                    metrics["http_endpoints"]["by_method"][method] = 0
                metrics["http_endpoints"]["by_method"][method] += 1
        except Exception:
            metrics["http_endpoints"] = {"error": "failed to collect"}

        return metrics
