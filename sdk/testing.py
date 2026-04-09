from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from core.runtime.runtime_context import RuntimeContext
from core.service.models import ServiceAuthConfig


class Noop:
    """Tiny placeholder object for unused RuntimeContext fields."""

    pass


class _HttpAdapter:
    def __init__(self, runtime: "PluginTestRuntime") -> None:
        self._runtime = runtime

    def register(self, endpoint: Any) -> None:
        self._runtime.register_http(endpoint)


class _OperationsAdapter:
    def __init__(self, runtime: "PluginTestRuntime") -> None:
        self._runtime = runtime

    def register_handler(self, op_type: str, handler: Any) -> None:
        self._runtime.register_operation_handler(op_type, handler)


@dataclass
class PluginTestRuntime:
    """
    Минимальный runtime для plugin-local unit-тестов.

    Цели:
    - дать BasePlugin валидный `create_context()`
    - дать рабочие `storage_*` helpers (in-memory)
    - позволить регистрировать/вызывать сервисы (очень упрощённо)

    Не пытается моделировать весь CoreRuntime.
    """

    storage_data: dict[tuple[str, str], object] = field(default_factory=dict)
    services: dict[str, Callable[..., Awaitable[Any]]] = field(default_factory=dict)
    registered_services: set[str] = field(default_factory=set)
    published_events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    registered_operation_handlers: dict[str, Any] = field(default_factory=dict)
    registered_http_endpoints: list[Any] = field(default_factory=list)

    def create_context(self) -> RuntimeContext:
        return RuntimeContext(
            storage=self,
            services=Noop(),
            http=_HttpAdapter(self),
            capabilities=Noop(),
            operations=_OperationsAdapter(self),
            state=Noop(),
            event_bus=Noop(),
        )

    # --- Storage (SDK helpers call these) ---
    async def storage_set(self, namespace: str, key: str, value: object) -> None:
        self.storage_data[(namespace, key)] = value

    async def storage_get(self, namespace: str, key: str) -> object:
        return self.storage_data.get((namespace, key))

    async def storage_delete(self, namespace: str, key: str) -> bool:
        return self.storage_data.pop((namespace, key), None) is not None

    async def storage_list_keys(self, namespace: str) -> list[str]:
        return [k for (ns, k) in self.storage_data.keys() if ns == namespace]

    # --- Services (PluginAPI helpers call these) ---
    async def register_service(
        self, name: str, func: Callable[..., Awaitable[Any]], **kwargs: Any
    ) -> None:
        # auth_config ignored in test runtime (bookkeeping only)
        _auth_config: ServiceAuthConfig | None = kwargs.get("auth_config")  # noqa: F841
        self.services[name] = func
        self.registered_services.add(name)

    async def unregister_service(self, name: str) -> None:
        self.services.pop(name, None)
        self.registered_services.discard(name)

    async def has_service(self, name: str) -> bool:
        return name in self.services

    async def call_service(self, name: str, *args: Any, **kwargs: Any) -> Any:
        if name not in self.services:
            raise RuntimeError(f"service not available in test runtime: {name}")
        return await self.services[name](*args, **kwargs)

    # --- Events / ops / http (no-op + bookkeeping) ---
    async def publish_event(self, event_type: str, payload: dict[str, Any]) -> None:
        self.published_events.append((event_type, dict(payload)))

    async def publish_operation_ready(self, operation_id: str, **extra: Any) -> None:
        return None

    async def subscribe_event(self, event_type: str, handler: Any) -> None:
        return None

    async def unsubscribe_event(self, event_type: str, handler: Any) -> None:
        return None

    def register_http(self, endpoint: Any) -> None:
        self.registered_http_endpoints.append(endpoint)

    def register_operation_handler(self, op_type: str, handler: Any) -> None:
        self.registered_operation_handlers[op_type] = handler


def make_test_context() -> RuntimeContext:
    """Утилита: минимальный валидный RuntimeContext для unit-тестов."""
    return RuntimeContext(
        storage=Noop(),
        services=Noop(),
        http=Noop(),
        capabilities=Noop(),
        operations=Noop(),
    )

