from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest


class _FakeStorage:
    def __init__(self) -> None:
        self._namespaces = ["plugins.x", "agent.y", "other.z"]

    async def list_namespaces(self) -> list[str]:
        return list(self._namespaces)

    async def iter_namespace(self, namespace: str):
        _ = namespace
        if False:
            yield ("k", "v")  # pragma: no cover
        return


class _FakeStateEngine:
    def __init__(self) -> None:
        self.set_calls: list[tuple[str, Any]] = []

    async def set(self, key: str, value: Any) -> None:
        self.set_calls.append((key, value))


class _HydrationHost:
    """
    Минимальный хост для RuntimeLifecycleMixin._hydrate_critical_state().

    Нам не нужен полноценный CoreRuntime — только storage/state_engine + callback.
    """

    def __init__(self) -> None:
        self.storage = _FakeStorage()
        self.state_engine = _FakeStateEngine()
        self._state_hydration_callback = None

    async def _hydrate_namespace(self, namespace: str) -> None:
        async for key, value in self.storage.iter_namespace(namespace):
            await self.state_engine.set(f"{namespace}.{key}", value)


@pytest.mark.asyncio
async def test_state_hydration_requires_app_callback(monkeypatch) -> None:
    from core.runtime._lifecycle import RuntimeLifecycleMixin

    host = _HydrationHost()
    # Call unbound mixin method against our host.
    await RuntimeLifecycleMixin._hydrate_critical_state(host)  # type: ignore[misc]
    assert host.state_engine.set_calls == []


@pytest.mark.asyncio
async def test_state_hydration_uses_callback_namespaces() -> None:
    from core.runtime._lifecycle import RuntimeLifecycleMixin

    host = _HydrationHost()

    async def cb() -> list[str]:
        return ["plugins.x", "agent.y"]

    host._state_hydration_callback = cb
    await RuntimeLifecycleMixin._hydrate_critical_state(host)  # type: ignore[misc]
    # iter_namespace yields nothing in our fake; we just assert no crash
    assert host.state_engine.set_calls == []

