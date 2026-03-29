"""
CoreRuntime - главный класс Core Runtime.

Объединяет все компоненты:
- EventBus
- ServiceRegistry
- StateEngine
- Storage
- PluginManager

Это kernel/runtime, а не backend-приложение.

Lifecycle (start/stop/shutdown/run/health) — см. core/runtime/_lifecycle.py.
"""

import asyncio
from typing import Any, Awaitable, Callable, Optional

from core.capability.registry import CapabilityRegistry
from core.dependency.resolver import DependencyResolver
from core.http.registry import HttpRegistry
from core.integration_registry import IntegrationRegistry
from core.kernel.context import KernelContext
from core.kernel.plugin_manager import PluginManager
from core.messaging.inmemory import InMemoryEventBus
from core.module.manager import ModuleManager
from core.operations.manager import OperationManager
from core.operations.worker import OperationWorker
from core.orchestration import (
    DockerOrchestrationBackend,
    NullOrchestrationBackend,
    OrchestrationService,
)
from core.runtime._lifecycle import RuntimeLifecycleMixin
from core.runtime.runtime_context import RuntimeContext
from core.service.registry import ServiceRegistry
from core.state_engine import StateEngine


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

        self.event_bus = InMemoryEventBus(storage=storage_port.storage)
        self.policy_engine = policy_engine

        default_timeout = config.service_call_timeout if config else None
        self.service_registry = ServiceRegistry(
            default_timeout=default_timeout,
            policy_engine=self.policy_engine,
            policy_engine_factory=service_policy_engine_factory,
            acl_wrapper_builder=service_acl_wrapper_builder,
        )

        self.state_engine = state_engine if state_engine is not None else StateEngine()
        self.storage = storage_port.storage
        self.vault = vault_port if vault_port else None
        self.http = HttpRegistry()
        self.integrations = IntegrationRegistry()
        self.capability_registry = capability_registry or CapabilityRegistry(
            check_capability_namespace_permission=capability_namespace_permission_checker,
            trust_level_to_privilege_mapper=trust_level_to_privilege_mapper,
        )
        self.operations = OperationManager(self)
        self.plugin_manager = PluginManager(self)
        module_path_prefix = (
            getattr(config, "module_path_prefix", "modules")
            if config is not None
            else "modules"
        )
        self.module_manager = ModuleManager(self, module_path_prefix=module_path_prefix)
        self.dependency_resolver = DependencyResolver(
            self.capability_registry, self.plugin_manager, self.storage
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
        # Optional app-level middleware factory. Core keeps no direct module dependency.
        self.event_validation_middleware_factory: Optional[Callable[[], Any]] = None
        # Optional app-level plugin isolation wiring. Core keeps no direct module dependency.
        self.plugin_storage_proxy_cls: Optional[type] = None
        self.plugin_service_proxy_cls: Optional[type] = None
        self.plugin_default_allowed_services: list[str] = []

        self.kernel_context: Optional[KernelContext] = KernelContext(
            {"service_registry": self.service_registry},
            self.state_engine,
            event_bus=self.event_bus,
        )

        self._running = False
        self._start_time: Optional[float] = None
        # App-defined list of namespaces to hydrate into state at startup.
        self.critical_state_prefixes: list[str] = list(critical_state_prefixes or [])
        # App-level monitoring delegates.
        self.runtime_health_check: Optional[
            Callable[["CoreRuntime"], Awaitable[dict[str, Any]]]
        ] = None
        self.runtime_metrics_collector: Optional[
            Callable[["CoreRuntime"], Awaitable[dict[str, Any]]]
        ] = None

        # Execution controller (опционально; выставляется модулем execution)
        self.execution_controller: Optional[Any] = None
        self.worker: Optional[OperationWorker] = None
        self._worker_task: Optional[asyncio.Task] = None

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

    def create_context(self) -> RuntimeContext:
        """
        Создать RuntimeContext для модулей и плагинов.

        Возвращает ограниченный контекст с только необходимыми компонентами.
        Используется модулями и плагинами вместо прямого доступа к runtime.
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

    # --- Delegation helpers ---

    async def call_service(self, name: str, *args: Any, **kwargs: Any) -> Any:
        return await self.service_registry.call(name, *args, **kwargs)

    async def has_service(self, name: str) -> bool:
        return await self.service_registry.has_service(name)

    async def publish_event(self, event_type: str, payload: dict[str, Any]) -> None:
        await self.event_bus.publish(event_type, payload)

    async def subscribe_event(
        self,
        event_type: str,
        handler: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        await self.event_bus.subscribe(event_type, handler)

    async def unsubscribe_event(
        self,
        event_type: str,
        handler: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        await self.event_bus.unsubscribe(event_type, handler)

    async def storage_get(self, namespace: str, key: str) -> Any:
        return await self.storage.get(namespace, key)

    async def storage_set(self, namespace: str, key: str, value: Any) -> None:
        await self.storage.set(namespace, key, value)

    async def storage_delete(self, namespace: str, key: str) -> bool:
        return bool(await self.storage.delete(namespace, key))

    async def storage_list_keys(self, namespace: str) -> list[str]:
        return list(await self.storage.list_keys(namespace))

    @property
    def state(self):
        """Алиас для state_engine. Плагины и Inspector используют runtime.state.get/set."""
        return self.state_engine

    @property
    def is_running(self) -> bool:
        """Запущен ли runtime."""
        return self._running
