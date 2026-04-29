"""
CoreServices — базовые сервисы ядра.

Минимальный набор сервисов для работы плагинов и модулей:
- Event-driven коммуникацию (event_bus)
- Service registry (вызов сервисов)
- Storage (ключ-значение)
- State management
- HTTP endpoints

Этот класс инкапсулирует "ядро ядра" — базовые примитивы,
которые требуются всем остальным компонентам.
"""

from typing import Any, Optional

from core.messaging_factory import create_event_bus
from core.ports import IEventBus, IServiceRegistry
from core.service.registry_factory import create_service_registry
from core.http.registry import HttpRegistry
from core.runtime.state_engine import StateEngine


class CoreServices:
    event_bus: IEventBus
    service_registry: IServiceRegistry
    """
    Базовые сервисы ядра — минимальный набор для работы плагинов.

    Отвечает за:
    - Event-driven коммуникацию (event_bus)
    - Service registry (вызов сервисов)
    - Storage (ключ-значение)
    - State management
    - HTTP endpoints

    Использование:
        services = CoreServices(storage_port, vault_port, config)
        await services.event_bus.publish("event.type", {"key": "value"})
        result = await services.service_registry.call("service.name", arg1, arg2)
    """

    def __init__(
        self,
        storage_port: Any,
        vault_port: Optional[Any] = None,
        config: Optional[Any] = None,
        *,
        policy_engine: Optional[Any] = None,
        service_policy_engine_factory: Optional[Any] = None,
        service_acl_wrapper_builder: Optional[Any] = None,
    ):
        """
        Инициализация базовых сервисов.

        Args:
            storage_port: CoreStoragePort для доступа к core storage
            vault_port: опциональный VaultStoragePort для доступа к vault (dual-mode)
            config: опциональная конфигурация (для shutdown_timeout, service_call_timeout)
            policy_engine: опциональный policy engine для service registry
            service_policy_engine_factory: фабрика policy engine для сервисов
            service_acl_wrapper_builder: builder для ACL wrapper сервисов
        """
        # Storage — основа всего
        self.storage = storage_port.storage
        self.vault = vault_port

        # Event bus — коммуникационная шина
        self.event_bus = create_event_bus(config=config, storage=self.storage)

        # Service registry — вызов сервисов
        self.service_registry = create_service_registry(
            config=config,
            policy_engine=policy_engine,
            policy_engine_factory=service_policy_engine_factory,
            acl_wrapper_builder=service_acl_wrapper_builder,
        )

        # State engine — управление состоянием
        self.state_engine = StateEngine()

        # HTTP registry — HTTP endpoints
        self.http = HttpRegistry()

    def create_context(self) -> dict[str, Any]:
        """
        Создать контекст для модулей и плагинов.

        Возвращает ограниченный набор компонентов.
        Используется модулями и плагинами вместо прямого доступа к services.

        Returns:
            Словарь с базовыми компонентами
        """
        return {
            "storage": self.storage,
            "vault": self.vault,
            "services": self.service_registry,
            "http": self.http,
            "state": self.state_engine,
            "event_bus": self.event_bus,
        }
