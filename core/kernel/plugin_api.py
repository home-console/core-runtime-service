from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from sdk.operations_events import OPERATION_READY_EVENT_TYPE, build_operation_ready_payload


class PluginAPI:
    """
    Thin plugin-facing API over runtime primitives.

    Goal:
    - keep plugin contract stable and language-agnostic
    - avoid exposing full runtime internals to plugin code
    """

    def __init__(
        self,
        *,
        service_registry: Any,
        event_bus: Any,
        storage: Any,
        operations: Any,
        http: Any,
    ) -> None:
        self._service_registry = service_registry
        self._event_bus = event_bus
        self._storage = storage
        self._operations = operations
        self._http = http

    async def call_service(self, name: str, *args: Any, **kwargs: Any) -> Any:
        return await self._service_registry.call(name, *args, **kwargs)

    async def has_service(self, name: str) -> bool:
        return await self._service_registry.has_service(name)

    async def register_service(
        self,
        name: str,
        func: Callable[..., Awaitable[Any]],
        *,
        resource: Optional[str] = None,
        admin_only: Optional[bool] = None,
        filter_result: bool = False,
        enforce_result: bool = False,
        preload_resource: Optional[Callable[[tuple, dict], Awaitable[Any]]] = None,
        inject_owner_param: Optional[str] = None,
        version: Optional[str] = None,
    ) -> None:
        register_with_acl = getattr(self._service_registry, "register_with_acl", None)
        if callable(register_with_acl):
            await register_with_acl(
                name,
                func,
                resource=resource,
                admin_only=admin_only,
                filter_result=filter_result,
                enforce_result=enforce_result,
                preload_resource=preload_resource,
                inject_owner_param=inject_owner_param,
                version=version,
            )
            return
        await self._service_registry.register(name, func, version=version)

    async def unregister_service(self, name: str) -> None:
        await self._service_registry.unregister(name)

    async def publish_event(self, event_type: str, payload: dict[str, Any]) -> None:
        await self._event_bus.publish(event_type, payload)

    async def publish_operation_ready(self, operation_id: str, **extra: Any) -> None:
        """Поставить операцию в очередь OperationWorker (событие G1, см. sdk.operations_events)."""
        payload = build_operation_ready_payload(operation_id, **extra)
        await self._event_bus.publish(OPERATION_READY_EVENT_TYPE, payload)

    async def subscribe_event(
        self,
        event_type: str,
        handler: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        await self._event_bus.subscribe(event_type, handler)

    async def unsubscribe_event(
        self,
        event_type: str,
        handler: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        await self._event_bus.unsubscribe(event_type, handler)

    async def storage_get(self, namespace: str, key: str) -> Any:
        return await self._storage.get(namespace, key)

    async def storage_set(self, namespace: str, key: str, value: Any) -> None:
        await self._storage.set(namespace, key, value)

    async def storage_delete(self, namespace: str, key: str) -> bool:
        return await self._storage.delete(namespace, key)

    async def storage_list_keys(self, namespace: str) -> list[str]:
        return await self._storage.list_keys(namespace)

    def register_http(self, endpoint: Any) -> None:
        self._http.register(endpoint)

    def register_operation_handler(self, op_type: str, handler: Any) -> None:
        self._operations.register_handler(op_type, handler)
