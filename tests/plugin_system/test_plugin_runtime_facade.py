from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from core.kernel.base_plugin import BasePlugin, PluginMetadata
from core.kernel.plugin_runtime_facade import PluginRuntimeFacade


class _DummyServiceRegistry:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.registered: list[tuple[str, Any, dict[str, Any]]] = []

    async def call(self, name: str, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((name, args, kwargs))
        return {"ok": True, "name": name}

    async def has_service(self, name: str) -> bool:
        return name == "logger.log"

    async def register_with_acl(self, name: str, func: Any, **kwargs: Any) -> None:
        self.registered.append((name, func, kwargs))


class _DummyEventBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        self.events.append((event_type, payload))


class _DummyStorage:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], Any] = {}

    async def get(self, namespace: str, key: str) -> Any:
        return self.values.get((namespace, key))

    async def set(self, namespace: str, key: str, value: Any) -> None:
        self.values[(namespace, key)] = value

    async def delete(self, namespace: str, key: str) -> bool:
        return self.values.pop((namespace, key), None) is not None

    async def list_keys(self, namespace: str) -> list[str]:
        return [k for ns, k in self.values.keys() if ns == namespace]


class _DummyHttp:
    def __init__(self) -> None:
        self.endpoints: list[Any] = []

    def register(self, endpoint: Any) -> None:
        self.endpoints.append(endpoint)


class _DummyOperations:
    def __init__(self) -> None:
        self.handlers: dict[str, Any] = {}

    def register_handler(self, op_type: str, handler: Any) -> None:
        self.handlers[op_type] = handler


@dataclass
class _DummyState:
    value: dict[str, Any]


class _TestPlugin(BasePlugin):
    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(name="test_plugin", version="1.0.0")


@pytest.mark.asyncio
async def test_plugin_runtime_facade_exposes_thin_api() -> None:
    runtime = PluginRuntimeFacade(
        storage=_DummyStorage(),
        service_registry=_DummyServiceRegistry(),
        http=_DummyHttp(),
        operations=_DummyOperations(),
        state=_DummyState(value={}),
        event_bus=_DummyEventBus(),
        capabilities={},
    )

    result = await runtime.api.call_service("logger.log", level="info")
    await runtime.api.publish_event("test.event", {"x": 1})
    await runtime.api.storage_set("n", "k", {"v": 1})

    assert result["ok"] is True
    assert runtime.event_bus.events == [("test.event", {"x": 1})]
    assert await runtime.api.storage_get("n", "k") == {"v": 1}


@pytest.mark.asyncio
async def test_base_plugin_helpers_use_runtime_api() -> None:
    runtime = PluginRuntimeFacade(
        storage=_DummyStorage(),
        service_registry=_DummyServiceRegistry(),
        http=_DummyHttp(),
        operations=_DummyOperations(),
        state=_DummyState(value={}),
        event_bus=_DummyEventBus(),
        capabilities={},
    )
    plugin = _TestPlugin(runtime)

    async def _handler() -> dict[str, bool]:
        return {"ok": True}

    await plugin.register_service("test.svc", _handler, admin_only=True)
    response = await plugin.call_service("logger.log", level="info")
    await plugin.publish_event("plugin.event", {"p": 1})
    await plugin.storage_set("ns", "key", "value")

    assert runtime.service_registry.registered
    assert response["ok"] is True
    assert runtime.event_bus.events[-1] == ("plugin.event", {"p": 1})
    assert await plugin.storage_get("ns", "key") == "value"
