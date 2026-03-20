"""Minimal kernel context for the core boundary."""

from __future__ import annotations

from typing import Any


class KernelContext:
    def __init__(self, service_registry: Any, state: Any) -> None:
        self._services = service_registry
        self._state = state

    def get_service(self, name: str):
        return self._services.get(name)

    def get_state(self, key: str):
        return self._state.get(key)

    def set_state(self, key: str, value):
        self._state.set(key, value)

    def emit(self, event):
        # TODO: будет реализовано позже
        pass