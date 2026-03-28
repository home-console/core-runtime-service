"""
PluginRuntime — контракт среды выполнения плагина (Protocol).

Только typing/Protocol. Никакой реализации.
Плагин получает opaque объект, удовлетворяющий этому контракту.
"""

from typing import Any, Protocol


class PluginAPI(Protocol):
    async def call_service(self, name: str, *args: Any, **kwargs: Any) -> Any: ...
    async def has_service(self, name: str) -> bool: ...
    async def publish_event(self, event_type: str, payload: dict[str, Any]) -> None: ...
    async def storage_get(self, namespace: str, key: str) -> Any: ...
    async def storage_set(self, namespace: str, key: str, value: Any) -> None: ...


class PluginRuntime(Protocol):
    """
    Контракт runtime, передаваемого плагину.
    Core предоставляет объект, совместимый с этим протоколом.
    """

    service_registry: Any
    event_bus: Any
    storage: Any
    state: Any
    operations: Any
    api: PluginAPI

    async def call_service(self, name: str, *args: Any, **kwargs: Any) -> Any: ...
    async def has_service(self, name: str) -> bool: ...
    async def publish_event(self, event_type: str, payload: dict[str, Any]) -> None: ...
    async def storage_get(self, namespace: str, key: str) -> Any: ...
    async def storage_set(self, namespace: str, key: str, value: Any) -> None: ...
    async def storage_delete(self, namespace: str, key: str) -> bool: ...
