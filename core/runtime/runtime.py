from __future__ import annotations

"""
CoreRuntime - главный класс Core Runtime.

Координирует работу всех компонентов через специализированные подсистемы.
Это kernel/runtime, а не backend-приложение.

Lifecycle (start/stop/shutdown/run/health) — см. core/runtime/_lifecycle.py.
"""

import asyncio
from typing import Any, Awaitable, Callable, List, Optional

from core.capability.component import CapabilityComponent
from core.kernel.context import KernelContext
from core.kernel.plugin_api import PluginAPI
from core.kernel.plugin_infrastructure import PluginInfrastructure
from core.operations.component import OperationsComponent
from core.runtime._lifecycle import RuntimeLifecycleMixin
from core.runtime.app_config import AppExtensionConfig
from core.runtime.monitor import RuntimeMonitor
from core.runtime.runtime_context import RuntimeContext
from core.runtime.services import CoreServices
from app.orchestration import NullOrchestrationBackend, OrchestrationService
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.orchestration import OrchestrationService


class CoreRuntime(RuntimeLifecycleMixin):
    """
    Главный класс Core Runtime.

    Координирует работу всех компонентов.
    Предоставляет единую точку доступа для плагинов.

    Lifecycle методы (start/stop/shutdown/run/health_check/get_metrics)
    унаследованы из RuntimeLifecycleMixin.
    """

    def __init__(
        self,
        storage_port: Any,
        config: Optional[Any] = None,
        vault_port: Optional[Any] = None,
        state_engine: Optional[Any] = None,
        *,
        policy_engine: Optional[Any] = None,
        service_policy_engine_factory: Optional[Callable[[Any | None], Any]] = None,
        service_acl_wrapper_builder: Optional[Any] = None,
        capability_registry: Optional[Any] = None,
        capability_namespace_permission_checker: Optional[Any] = None,
        trust_level_to_privilege_mapper: Optional[Any] = None,
        critical_state_prefixes: Optional[list[str]] = None,
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
        self._config = config
        self.config = config
        self.policy_engine = policy_engine

        # Уровень 1: Базовые сервисы ядра
        self.services = CoreServices(
            storage_port=storage_port,
            vault_port=vault_port,
            config=config,
            policy_engine=policy_engine,
            service_policy_engine_factory=service_policy_engine_factory,
            service_acl_wrapper_builder=service_acl_wrapper_builder,
        )

        # Уровень 2: Capability компонент
        self.capabilities = CapabilityComponent(
            capability_namespace_permission_checker=capability_namespace_permission_checker,
            trust_level_to_privilege_mapper=trust_level_to_privilege_mapper,
            policy_engine=policy_engine,
            service_policy_engine_factory=service_policy_engine_factory,
            service_acl_wrapper_builder=service_acl_wrapper_builder,
        )

        # Уровень 3: Operations компонент
        self.operations = OperationsComponent(self)

        # Stable plugin-facing API over runtime primitives.
        self.api = PluginAPI(
            service_registry=self.services.service_registry,
            event_bus=self.services.event_bus,
            storage=self.services.storage,
            operations=self.operations,
            http=self.services.http,
        )

        # Уровень 4: Инфраструктура плагинов (использует capability_registry из компонента)
        self.plugins = PluginInfrastructure(
            runtime=self,
            capability_registry=self.capabilities.registry,
            config=config,
        )

        # Координация и контексты
        self.kernel_context: Optional[KernelContext] = KernelContext(
            {"service_registry": self.services.service_registry},
            self.services.state_engine if state_engine is None else state_engine,
            event_bus=self.services.event_bus,
        )

        # Agent control plane components. Initialized in start() when SecretStore is ready.
        self.agent_manager: Optional[Any] = None
        self.agent_registry: Optional[Any] = None
        self.deployment_tracker: Optional[Any] = None
        self.mtls_ca: Optional[Any] = None
        # SecretStore (vault) — выставляется в main; используется credentials и inspector в debug
        self.secret_store: Optional[Any] = None
        # StorageManager (core + vault) — выставляется в main для модуля credentials
        self.storage_manager: Optional[Any] = None
        
        # App-level extension hooks (вынесено в app_config для соблюдения границ ядра)
        self.app_config: AppExtensionConfig = AppExtensionConfig.create()

        # App-level плагины и модули доступны через self.plugins
        # Для обратной совместимости добавлены property-методы ниже

        self._running = False
        self._start_time: Optional[float] = None
        
        # Metrics registry — dependency injection вместо global singleton
        from core.observability.metrics import MetricsRegistry
        self._metrics_registry = MetricsRegistry()

        # Rate limiter — per-runtime instance (do not use global singleton)
        from core.observability.rate_limiter import PluginRateLimiter
        self._rate_limiter = PluginRateLimiter()

        # Operation context — per-runtime instance (do not use module-level globals)
        from core.runtime.operation_context import OperationContext
        self._operation_context = OperationContext()
        
        # App-defined list of namespaces to hydrate into state at startup.
        self.critical_state_prefixes: list[str] = list(critical_state_prefixes or [])

        # Уровень 5: Monitoring компонент
        self.monitor = RuntimeMonitor(
            runtime=self,
            health_check_delegate=None,  # Выставляется из app при необходимости
            metrics_collector_delegate=None,  # Выставляется из app при необходимости
        )

        # Orchestration service — создаётся в app-layer, ядро только хранит ссылку.
        # Если None, используется NullOrchestrationBackend (отключенная оркестрация).
        self.orchestration_service: Optional["OrchestrationService"] = orchestration_service
        if self.orchestration_service is None:
            backend_mode = str(getattr(config, "orchestration_backend", "none")).lower()
            if backend_mode == "none":
                self.orchestration_service = OrchestrationService(NullOrchestrationBackend())

        # Backward-compatible runtime worker task handle (used in tests and lifecycle helpers).
        self._worker_task: Optional[asyncio.Task[Any]] = None

    def create_context(self) -> RuntimeContext:
        """
        Создать RuntimeContext для модулей и плагинов.

        Возвращает ограниченный контекст с только необходимыми компонентами.
        Используется модулями и плагинами вместо прямого доступа к runtime.
        """
        return RuntimeContext(
            storage=self.services.storage,
            vault=self.services.vault,
            services=self.services.service_registry,
            http=self.services.http,
            capabilities=self.capabilities.registry,
            operations=self.operations.manager,
            state=self.services.state_engine,
            event_bus=self.services.event_bus,
            metrics=self._metrics_registry,
            rate_limiter=self._rate_limiter,
            operation_context=self._operation_context,
        )

    # --- Delegation helpers (через services) ---

    async def call_service(self, name: str, *args: Any, **kwargs: Any) -> Any:
        return await self.services.service_registry.call(name, *args, **kwargs)

    async def has_service(self, name: str) -> bool:
        return await self.services.service_registry.has_service(name)

    async def publish_event(self, event_type: str, payload: dict[str, Any]) -> None:
        await self.services.event_bus.publish(event_type, payload)

    async def subscribe_event(
        self,
        event_type: str,
        handler: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        await self.services.event_bus.subscribe(event_type, handler)

    async def unsubscribe_event(
        self,
        event_type: str,
        handler: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        await self.services.event_bus.unsubscribe(event_type, handler)

    async def storage_get(self, namespace: str, key: str) -> Any:
        return await self.services.storage.get(namespace, key)

    async def storage_set(self, namespace: str, key: str, value: Any) -> None:
        await self.services.storage.set(namespace, key, value)

    async def storage_delete(self, namespace: str, key: str) -> bool:
        return bool(await self.services.storage.delete(namespace, key))

    async def storage_list_keys(self, namespace: str) -> list[str]:
        return list(await self.services.storage.list_keys(namespace))

    @property
    def state(self):
        """Алиас для state_engine. Плагины и Inspector используют runtime.state.get/set."""
        return self.services.state_engine

    @property
    def is_running(self) -> bool:
        """Запущен ли runtime."""
        return self._running

    # --- Property-методы для обратной совместимости ---
    # Направляют к self.services для старого кода

    @property
    def event_bus(self) -> Any:
        """Обратная совместимость: event_bus через services."""
        return self.services.event_bus

    @property
    def service_registry(self) -> Any:
        """Обратная совместимость: service_registry через services."""
        return self.services.service_registry

    @property
    def state_engine(self) -> Any:
        """Обратная совместимость: state_engine через services."""
        return self.services.state_engine

    @property
    def storage(self) -> Any:
        """Обратная совместимость: storage через services."""
        return self.services.storage

    @property
    def vault(self) -> Any:
        """Обратная совместимость: vault через services."""
        return self.services.vault

    @property
    def http(self) -> Any:
        """Обратная совместимость: http через services."""
        return self.services.http

    # --- Property-методы для обратной совместимости (плагины) ---
    # Направляют к self.plugins для старого кода

    @property
    def plugin_manager(self) -> Any:
        """Обратная совместимость: plugin_manager через plugins."""
        return self.plugins.plugin_manager

    @property
    def module_manager(self) -> Any:
        """Обратная совместимость: module_manager через plugins."""
        return self.plugins.module_manager

    @property
    def dependency_resolver(self) -> Any:
        raise AttributeError(
            "dependency_resolver has been removed; use runtime.plugins.lifecycle_policy "
            "and runtime.plugins.integrity_checker"
        )

    @property
    def integrations(self) -> Any:
        """Обратная совместимость: integrations через plugins."""
        return self.plugins.integrations

    # --- Property-методы для обратной совместимости (capabilities) ---
    # Направляют к self.capabilities для старого кода

    @property
    def capability_registry(self) -> Any:
        """Обратная совместимость: capability_registry через capabilities."""
        return self.capabilities.registry

    # --- Property-методы для обратной совместимости (operations) ---
    # Направляют к self.operations для старого кода

    @property
    def worker(self) -> Any:
        """Обратная совместимость: worker через operations."""
        return self.operations.worker

    @worker.setter
    def worker(self, value: Any) -> None:
        """Обратная совместимость: установка worker."""
        self.operations.worker = value

    @property
    def execution_controller(self) -> Any:
        """Обратная совместимость: execution_controller через operations."""
        return self.operations.execution_controller

    @execution_controller.setter
    def execution_controller(self, value: Any) -> None:
        """Обратная совместимость: установка execution_controller."""
        self.operations.execution_controller = value

    # --- App extension hooks ---

    def set_state_hydration_callback(
        self,
        callback: Callable[[], Awaitable[List[str]]]
    ) -> None:
        """
        Установить callback для гидратации state при старте.

        App-layer предоставляет callback который возвращает список namespaces
        для гидратации в StateEngine. Это устраняет необходимость ядра знать
        о доменных префиксах.

        Args:
            callback: Async callback возвращающий список namespaces
        """
        self._state_hydration_callback = callback

    # --- Property-методы для обратной совместимости (app_config) ---
    # Направляют к self.app_config для старого кода

    @property
    def event_validation_middleware_factory(self) -> Any:
        """Обратная совместимость: event_validation_middleware_factory через app_config."""
        return self.app_config.event_validation_middleware_factory

    @event_validation_middleware_factory.setter
    def event_validation_middleware_factory(self, value: Any) -> None:
        """Обратная совместимость: установка event_validation_middleware_factory."""
        self.app_config.event_validation_middleware_factory = value

    @property
    def plugin_storage_proxy_cls(self) -> Any:
        """Обратная совместимость: plugin_storage_proxy_cls через app_config."""
        return self.app_config.plugin_storage_proxy_cls

    @plugin_storage_proxy_cls.setter
    def plugin_storage_proxy_cls(self, value: Any) -> None:
        """Обратная совместимость: установка plugin_storage_proxy_cls."""
        self.app_config.plugin_storage_proxy_cls = value

    @property
    def plugin_service_proxy_cls(self) -> Any:
        """Обратная совместимость: plugin_service_proxy_cls через app_config."""
        return self.app_config.plugin_service_proxy_cls

    @plugin_service_proxy_cls.setter
    def plugin_service_proxy_cls(self, value: Any) -> None:
        """Обратная совместимость: установка plugin_service_proxy_cls."""
        self.app_config.plugin_service_proxy_cls = value

    @property
    def plugin_default_allowed_services(self) -> Any:
        """Обратная совместимость: plugin_default_allowed_services через app_config."""
        return self.app_config.plugin_default_allowed_services

    @plugin_default_allowed_services.setter
    def plugin_default_allowed_services(self, value: Any) -> None:
        """Обратная совместимость: установка plugin_default_allowed_services."""
        self.app_config.plugin_default_allowed_services = value
