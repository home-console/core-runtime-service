from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.skills.registry import SkillRegistry


class _FakeBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list] = {}

    async def subscribe(self, event_type: str, handler) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    async def publish(self, event_type: str, payload: dict) -> None:
        for handler in self._handlers.get(event_type, []):
            await handler(payload)


@pytest.mark.asyncio
async def test_plugin_loaded_unloaded_updates_registry():
    """Integration-style: SkillsModule handlers on internal.plugin.* events."""
    from modules.skills.module import SkillsModule

    runtime = SimpleNamespace(event_bus=_FakeBus())
    mod = SkillsModule(runtime)

    mod.context = SimpleNamespace(
        services=SimpleNamespace(
            register=AsyncMock(),
            unregister=AsyncMock(),
        ),
        http=MagicMock(),
    )

    await mod.register()

    await runtime.event_bus.publish(
        "internal.plugin.loaded",
        {
            "plugin_name": "demo",
            "plugin_version": "1.2.3",
            "skills": [{"name": "snap", "intent": "take snapshot"}],
        },
    )
    assert mod.registry.get("demo.snap") is not None
    assert mod.registry.get("demo.snap").plugin_version == "1.2.3"

    await runtime.event_bus.publish(
        "internal.plugin.unloaded",
        {"plugin_name": "demo"},
    )
    assert mod.registry.list_skills() == []

    await mod.stop()
