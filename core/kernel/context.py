"""Minimal kernel context for the core boundary."""

from __future__ import annotations

from typing import Any


class KernelContext:
    def __init__(self, service_registry: Any, state: Any, *, event_bus: Any = None) -> None:
        self._services = service_registry
        self._state = state
        self._event_bus = event_bus

    def get_service(self, name: str):
        # Contract: `_services` is a dict-like registry: `self._services[name]`.
        return self._services[name]

    def get_state(self, key: str):
        return self._state.get(key)

    def set_state(self, key: str, value):
        self._state.set(key, value)

    async def emit(self, event_type: str, data: dict[str, Any]) -> None:
        await self._event_bus.publish(event_type, data)