from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from core.kernel.plugin_api import PluginAPI
from core.runtime.runtime_context import RuntimeContext


@dataclass(frozen=True)
class PluginRuntimeFacade:
    """
    Минимальный совместимый facade вместо полного CoreRuntime.

    SECURITY: не содержит plugin_manager/module_manager/orchestration и т.п.
    """

    # Common surfaces used by existing plugins
    storage: Any
    service_registry: Any
    http: Any
    operations: Any
    state: Any
    event_bus: Any
    capabilities: Any
    vault: Optional[Any] = None
    config: Optional[Any] = None
    agent_manager: Optional[Any] = None
    agent_registry: Optional[Any] = None
    api: Optional[PluginAPI] = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "api",
            PluginAPI(
                service_registry=self.service_registry,
                event_bus=self.event_bus,
                storage=self.storage,
                operations=self.operations,
                http=self.http,
            ),
        )

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

    async def register_service(
        self, name: str, func: Callable[..., Awaitable[Any]], **kwargs: Any
    ) -> None:
        """Register a service via PluginAPI."""
        if self.api is None:
            raise RuntimeError("PluginAPI not initialized")
        await self.api.register_service(name, func, **kwargs)

    async def unregister_service(self, name: str) -> None:
        """Unregister a service via PluginAPI."""
        if self.api is None:
            raise RuntimeError("PluginAPI not initialized")
        await self.api.unregister_service(name)

    def register_http(self, endpoint: Any) -> None:
        """Register an HTTP endpoint via PluginAPI."""
        if self.api is None:
            raise RuntimeError("PluginAPI not initialized")
        self.api.register_http(endpoint)

    def register_operation_handler(self, op_type: str, handler: Any) -> None:
        """Register an operation handler via PluginAPI."""
        if self.api is None:
            raise RuntimeError("PluginAPI not initialized")
        self.api.register_operation_handler(op_type, handler)

    def create_context(self) -> RuntimeContext:
        return RuntimeContext(
            storage=self.storage,
            vault=self.vault,
            services=self.service_registry,
            http=self.http,
            capabilities=self.capabilities,
            operations=self.operations,
            state=self.state,
        )
