"""
RuntimeContext - ограниченный контекст для модулей и плагинов.

Предоставляет только необходимые компоненты ядра без прямого доступа
к внутренним деталям (plugin_manager, module_manager, event_bus напрямую).
"""

from dataclasses import dataclass
from typing import Any, Optional

from core.capability.registry import CapabilityRegistry
from core.http.registry import HttpRegistry
from core.operations.manager import OperationManager
from core.observability.metrics import MetricsRegistry
from core.observability.rate_limiter import PluginRateLimiter
from core.service.registry import ServiceRegistry
from core.runtime.operation_context import OperationContext


@dataclass
class RuntimeContext:
    """
    Ограниченный контекст для модулей и плагинов.

    Предоставляет только публичный API ядра:
    - storage: доступ к storage (через StoragePort)
    - vault: доступ к vault storage (если dual-mode)
    - services: ServiceRegistry для регистрации/вызова сервисов
    - http: HttpRegistry для регистрации HTTP endpoints
    - capabilities: CapabilityRegistry для регистрации capabilities
    - operations: OperationManager для выполнения операций

    НЕ предоставляет:
    - plugin_manager, module_manager (внутренние детали)
    - event_bus (используется через operations/events)
    - Прямой доступ к runtime (только через контекст)
    """

    # Storage (обязательные — без default)
    storage: Any  # Core storage (через StoragePort)
    services: ServiceRegistry  # Service registry
    http: HttpRegistry  # HTTP registry
    capabilities: CapabilityRegistry  # Capability registry
    operations: OperationManager  # Operations manager

    # Опциональные (с default — должны идти после обязательных)
    vault: Optional[Any] = None  # Vault storage port (если dual-mode)
    state: Optional[Any] = None  # StateEngine (для быстрого доступа к state)
    event_bus: Optional[Any] = None  # InMemoryEventBus (pub/sub)
    metrics: Optional[MetricsRegistry] = None  # Observability metrics registry (per-runtime)
    rate_limiter: Optional[PluginRateLimiter] = None  # Plugin rate limiter (per-runtime)
    operation_context: Optional[OperationContext] = None  # Operation context (per-runtime)

    def __post_init__(self):
        """Валидация обязательных полей."""
        if self.storage is None:
            raise ValueError("storage is required")
        if self.services is None:
            raise ValueError("services is required")
        if self.http is None:
            raise ValueError("http is required")
        if self.capabilities is None:
            raise ValueError("capabilities is required")
        if self.operations is None:
            raise ValueError("operations is required")


def build_synthetic_runtime_context(runtime: Any) -> "RuntimeContext":
    """
    Собрать RuntimeContext из полей произвольного объекта (тестовые даблы, SimpleNamespace).

    Используется когда нет настоящего CoreRuntime.create_context().
    """
    from unittest.mock import MagicMock

    def _need(val: Any) -> Any:
        return MagicMock() if val is None else val

    storage = getattr(runtime, "storage", None)
    services = (
        getattr(runtime, "service_registry", None)
        or getattr(runtime, "services", None)
    )
    http = getattr(runtime, "http", None)
    capabilities = (
        getattr(runtime, "capabilities", None)
        or getattr(runtime, "capability_registry", None)
    )
    operations = getattr(runtime, "operations", None)

    return RuntimeContext(
        storage=_need(storage),
        services=_need(services),
        http=_need(http),
        capabilities=_need(capabilities),
        operations=_need(operations),
        vault=getattr(runtime, "vault", None),
        state=getattr(runtime, "state_engine", None) or getattr(runtime, "state", None),
        event_bus=getattr(runtime, "event_bus", None),
        metrics=getattr(runtime, "metrics", None),
        rate_limiter=getattr(runtime, "rate_limiter", None),
        operation_context=getattr(runtime, "operation_context", None),
    )


def resolve_runtime_context_for_host(runtime: Any, *, owner: str) -> "RuntimeContext":
    """
    Получить RuntimeContext из уже готового контекста или с рантайма (create_context / синтетика).

    Поддерживает:
    - CoreRuntime.create_context() → RuntimeContext
    - unittest.mock: create_context() вернул Mock → синтетика по полям runtime
    - тестовые объекты без create_context() (например SimpleNamespace) → синтетика
    """
    create_context = getattr(runtime, "create_context", None)
    if not callable(create_context):
        return build_synthetic_runtime_context(runtime)

    maybe_context = create_context()
    if isinstance(maybe_context, RuntimeContext):
        return maybe_context
    # Mock по умолчанию возвращает None; иные тестовые даблы — тоже через синтетику
    if maybe_context is None:
        return build_synthetic_runtime_context(runtime)
    if type(maybe_context).__module__ == "unittest.mock":
        return build_synthetic_runtime_context(runtime)

    raise TypeError(
        f"{owner}: create_context() must return RuntimeContext (got {type(maybe_context).__name__})"
    )
