"""
Ports — абстрактные интерфейсы для замены реализаций.

IEventBus и IServiceRegistry описывают контракты которым должны
соответствовать любые реализации (InMemory, Redis, gRPC, etc).
"""

from __future__ import annotations

from typing import Any, Callable, Protocol, runtime_checkable

from core.messaging import AnyEventHandler, EventBusMiddleware
from core.service.registry import ServiceAuthConfig, ServiceMiddleware


@runtime_checkable
class IEventBus(Protocol):
    async def publish(self, event_type: str, payload: dict[str, Any]) -> None: ...

    def subscribe(
        self,
        event_type: str,
        handler: AnyEventHandler,
        *,
        priority: int = 0,
    ) -> None: ...

    def unsubscribe(self, event_type: str, handler: AnyEventHandler) -> None: ...

    async def claim_event(self, event_id: str, worker_id: str) -> bool: ...

    async def add_middleware(self, middleware: EventBusMiddleware) -> None: ...

    async def remove_middleware(self, middleware: EventBusMiddleware) -> None: ...

    async def list_middleware(self) -> list[str]: ...

    async def get_unprocessed_events(self) -> list[dict[str, Any]]: ...

    async def is_event_processed(self, event_id: str) -> bool: ...

    async def mark_event_processed(self, event_id: str) -> None: ...


@runtime_checkable
class IServiceRegistry(Protocol):
    async def register(
        self,
        service_name: str,
        handler: Callable,
        *,
        version: str = "1.0.0",
        timeout: float | None = None,
        resource: str | None = None,
        action: str | None = None,
    ) -> None: ...

    async def register_with_acl(
        self,
        service_name: str,
        handler: Callable,
        **kwargs: Any,
    ) -> None: ...

    async def unregister(self, service_name: str) -> None: ...

    async def call(self, service_name: str, *args: Any, **kwargs: Any) -> Any: ...

    async def call_without_timeout(
        self, service_name: str, *args: Any, **kwargs: Any
    ) -> Any: ...

    async def has_service(self, service_name: str) -> bool: ...

    async def list_services(self) -> list[str]: ...

    async def add_middleware(self, middleware: ServiceMiddleware) -> None: ...

    async def remove_middleware(self, middleware: ServiceMiddleware) -> None: ...

    async def get_auth_config(self, service_name: str) -> ServiceAuthConfig | None: ...

    async def set_auth_config(
        self, service_name: str, config: ServiceAuthConfig
    ) -> None: ...

