from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from core.exceptions import ForbiddenError
from core.kernel.plugin_isolation import (
    EventBusProxy,
    HttpRegistryProxy,
    NamespacedStorageProxy,
    OperationRegistryProxy,
    ServiceRegistryProxy,
    assert_plugin_namespace_allowed,
)


class _ServiceRegistry:
    def __init__(self) -> None:
        self.registered: list[str] = []
        self.unregistered: list[str] = []

    async def call(self, service_name: str, *args: Any, **kwargs: Any) -> Any:
        return {"service": service_name, "args": args, "kwargs": kwargs}

    async def has_service(self, service_name: str) -> bool:
        return True

    async def register(self, name: str, func: Any, **kwargs: Any) -> None:
        self.registered.append(name)

    async def unregister(self, name: str) -> None:
        self.unregistered.append(name)


class _Storage:
    async def get(self, namespace: str, key: str) -> Any:
        return (namespace, key)

    async def set(self, namespace: str, key: str, value: Any) -> None:
        return None

    async def delete(self, namespace: str, key: str) -> bool:
        return True

    async def list_keys(self, namespace: str) -> list[str]:
        return [namespace]


class _EventBus:
    def __init__(self) -> None:
        self.published: list[str] = []
        self.subscribed: list[str] = []

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        self.published.append(event_type)

    async def subscribe(self, event_type: str, handler: Any) -> None:
        self.subscribed.append(event_type)

    async def unsubscribe(self, event_type: str, handler: Any) -> None:
        pass


class _Operations:
    def __init__(self) -> None:
        self.handlers: dict[str, Any] = {}

    def register_handler(self, op_type: str, handler: Any) -> None:
        self.handlers[op_type] = handler

    def unregister_handler(self, op_type: str) -> None:
        self.handlers.pop(op_type, None)

    def list_handler_types(self) -> list[str]:
        return list(self.handlers)


class _HttpRegistry:
    def __init__(self) -> None:
        self.endpoints: list[Any] = []

    def register(self, endpoint: Any) -> None:
        self.endpoints.append(endpoint)

    def list(self) -> list[Any]:
        return list(self.endpoints)


@pytest.mark.asyncio
async def test_service_registry_proxy_blocks_registration_outside_declared_namespaces() -> None:
    registry = _ServiceRegistry()
    proxy = ServiceRegistryProxy(
        registry,
        allowed_services=["logger.*"],
        plugin_name="owner",
        allowed_provided_services=["shared.allowed"],
    )

    await proxy.register("owner.local", lambda: None)
    await proxy.register("shared.allowed", lambda: None)
    with pytest.raises(ForbiddenError):
        await proxy.register("other.service", lambda: None)
    with pytest.raises(ForbiddenError):
        await proxy.unregister("other.service")


@pytest.mark.parametrize(
    "namespace",
    ["runtime", "runtime.backup", "hc.internal", "system.auth", "core.kernel"],
)
def test_reserved_namespace_rejected(namespace: str) -> None:
    with pytest.raises(ValueError, match="Reserved"):
        assert_plugin_namespace_allowed(namespace)


def test_namespaced_storage_proxy_rejects_reserved_allowed_namespace() -> None:
    with pytest.raises(ValueError, match="Reserved"):
        NamespacedStorageProxy(
            _Storage(),
            namespace="my_plugin",
            allowed_namespaces=["runtime.evil"],
        )


@pytest.mark.asyncio
async def test_namespaced_storage_proxy_blocks_undeclared_storage_namespace() -> None:
    proxy = NamespacedStorageProxy(
        _Storage(),
        namespace="owner",
        allowed_namespaces=["shared"],
    )

    assert await proxy.get("owner", "key") == ("owner", "key")
    assert await proxy.get("shared", "key") == ("shared", "key")
    with pytest.raises(ForbiddenError):
        await proxy.get("other", "key")


@pytest.mark.asyncio
async def test_event_bus_proxy_blocks_subscribe_to_reserved_events() -> None:
    bus = _EventBus()
    proxy = EventBusProxy(bus, "owner")

    await proxy.subscribe("internal.device_ready", lambda _e, _p: None)
    with pytest.raises(ForbiddenError):
        await proxy.subscribe("runtime.admin.secret", lambda _e, _p: None)


@pytest.mark.asyncio
async def test_event_bus_proxy_requires_declared_subscribe_pattern() -> None:
    bus = _EventBus()
    proxy = EventBusProxy(
        bus,
        "owner",
        subscribed_events=["automation.triggered"],
    )

    await proxy.subscribe("automation.triggered", lambda _e, _p: None)
    with pytest.raises(ForbiddenError):
        await proxy.subscribe("automation.other", lambda _e, _p: None)


@pytest.mark.asyncio
async def test_event_bus_proxy_requires_declared_publish_namespace() -> None:
    bus = _EventBus()
    proxy = EventBusProxy(bus, "owner", allowed_events=["external.ready"])

    await proxy.publish("owner.ready", {})
    await proxy.publish("external.ready", {})
    with pytest.raises(ForbiddenError):
        await proxy.publish("other.ready", {})


def test_http_registry_proxy_blocks_endpoint_for_foreign_service() -> None:
    registry = _HttpRegistry()
    proxy = HttpRegistryProxy(registry, "owner", allowed_provided_services=["shared.api"])

    proxy.register(SimpleNamespace(service="owner.endpoint"))
    proxy.register(SimpleNamespace(service="shared.api"))
    with pytest.raises(ForbiddenError):
        proxy.register(SimpleNamespace(service="other.endpoint"))


@pytest.mark.asyncio
async def test_operation_proxy_wraps_handlers_with_restricted_runtime() -> None:
    operations = _Operations()
    proxy = OperationRegistryProxy(operations, "owner")
    restricted_runtime = SimpleNamespace(marker="facade")
    raw_runtime = SimpleNamespace(marker="raw")
    proxy.set_restricted_runtime(restricted_runtime)

    async def handler(runtime: Any, operation: Any) -> str:
        return runtime.marker

    proxy.register_handler("owner.op", handler)
    result = await operations.handlers["owner.op"](raw_runtime, SimpleNamespace(params={}))

    assert result == "facade"
    with pytest.raises(ForbiddenError):
        proxy.register_handler("other.op", handler)
