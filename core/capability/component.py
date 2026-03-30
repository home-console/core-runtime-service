"""
CapabilityComponent — компонент управления capabilities и security.

Отвечает за:
- Реестр capabilities (capability_registry)
- Policy engine (policy_engine)
- Проверку прав доступа (capability_namespace_permission_checker)
- Маппинг trust level к privilege (trust_level_to_privilege_mapper)

Этот класс инкапсулирует всю security-логику,
освобождая CoreRuntime от этих обязанностей.
"""

from typing import Any, Callable, Optional

from core.capability.registry import CapabilityRegistry


class CapabilityComponent:
    """
    Компонент управления capabilities и security.

    Отвечает за:
    - Реестр capabilities
    - Policy engine для security-политик
    - Проверку прав доступа к namespace'ам capabilities
    - Маппинг trust level к privilege

    Использование:
        cap_component = CapabilityComponent(
            capability_namespace_permission_checker=checker,
            trust_level_to_privilege_mapper=mapper
        )
        cap_component.registry.register(...)
        policy = cap_component.policy_engine.evaluate(...)
    """

    def __init__(
        self,
        capability_namespace_permission_checker: Optional[Callable[..., bool]] = None,
        trust_level_to_privilege_mapper: Optional[Callable[..., Any]] = None,
        policy_engine: Optional[Any] = None,
        service_policy_engine_factory: Optional[Callable[..., Any]] = None,
        service_acl_wrapper_builder: Optional[Callable[..., Any]] = None,
    ):
        """
        Инициализация компонента capabilities.

        Args:
            capability_namespace_permission_checker: функция проверки прав доступа к namespace
            trust_level_to_privilege_mapper: функция маппинга trust level к privilege
            policy_engine: опциональный policy engine (если None, создаётся внутри)
            service_policy_engine_factory: фабрика policy engine для сервисов
            service_acl_wrapper_builder: builder для ACL wrapper сервисов
        """
        # Capability registry — основной реестр
        self.registry = CapabilityRegistry(
            check_capability_namespace_permission=capability_namespace_permission_checker,
            trust_level_to_privilege_mapper=trust_level_to_privilege_mapper,
        )

        # Policy engine — security-политики
        self.policy_engine = policy_engine

        # Фабрики для service registry
        self.service_policy_engine_factory = service_policy_engine_factory
        self.service_acl_wrapper_builder = service_acl_wrapper_builder

    def create_context(self) -> dict[str, Any]:
        """
        Создать контекст компонента capabilities.

        Возвращает основные компоненты для работы с capabilities и security.

        Returns:
            Словарь с компонентами capabilities
        """
        return {
            "capability_registry": self.registry,
            "policy_engine": self.policy_engine,
            "service_policy_engine_factory": self.service_policy_engine_factory,
            "service_acl_wrapper_builder": self.service_acl_wrapper_builder,
        }
