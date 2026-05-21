"""SK5 full: skills registry persisted in runtime storage."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.skills.module import SkillsModule
from modules.skills.persist import (
    SKILLS_NAMESPACE,
    delete_plugin_skills,
    hydrate_registry_from_storage,
    persist_plugin_skills,
)
from modules.skills.registry import SkillRegistry
from tests.conftest import InMemoryStorageAdapter


def _runtime_with_storage(adapter: InMemoryStorageAdapter, **extra) -> SimpleNamespace:
    return SimpleNamespace(storage=adapter, **extra)


@pytest.mark.asyncio
async def test_persist_and_hydrate_roundtrip() -> None:
    adapter = InMemoryStorageAdapter()
    runtime = _runtime_with_storage(adapter)

    ok = await persist_plugin_skills(
        runtime,
        "demo",
        "2.0.0",
        [{"name": "ping", "intent": "health", "service": "demo.skill.ping"}],
    )
    assert ok is True

    reg = SkillRegistry()
    count = await hydrate_registry_from_storage(reg, runtime)
    assert count == 1
    rec = reg.get("demo.ping")
    assert rec is not None
    assert rec.plugin_version == "2.0.0"
    assert rec.service == "demo.skill.ping"


@pytest.mark.asyncio
async def test_delete_plugin_skills_removes_storage() -> None:
    adapter = InMemoryStorageAdapter()
    runtime = _runtime_with_storage(adapter)
    await persist_plugin_skills(
        runtime, "gone", "1.0.0", [{"name": "x", "intent": "do x"}]
    )
    await delete_plugin_skills(runtime, "gone")
    assert await adapter.get(SKILLS_NAMESPACE, "gone") is None
    index = await adapter.get(SKILLS_NAMESPACE, "_index")
    assert index is not None
    assert "gone" not in (index.get("plugins") or [])


@pytest.mark.asyncio
async def test_restart_from_storage_without_plugins_dir() -> None:
    """Cold start: storage has skills, plugins_dir missing — registry still works."""
    adapter = InMemoryStorageAdapter()
    await persist_plugin_skills(
        _runtime_with_storage(adapter),
        "stored_only",
        "1.0.0",
        [{"name": "snap", "intent": "snapshot"}],
    )

    runtime = SimpleNamespace(
        storage=adapter,
        _config=SimpleNamespace(plugins_dir="/nonexistent/plugins"),
        event_bus=None,
    )
    mod = SkillsModule(runtime)
    mod.context = SimpleNamespace(
        services=SimpleNamespace(register=AsyncMock(), unregister=AsyncMock()),
        http=MagicMock(),
    )
    await mod.register()
    await mod.start()

    listed = await mod._service_list()
    assert listed["total"] == 1
    assert listed["items"][0]["id"] == "stored_only.snap"

    await mod.stop()


@pytest.mark.asyncio
async def test_plugin_events_update_storage(tmp_path: Path) -> None:
    from modules.skills.module import SkillsModule

    class _FakeBus:
        def __init__(self) -> None:
            self._handlers: dict[str, list] = {}

        async def subscribe(self, event_type: str, handler) -> None:
            self._handlers.setdefault(event_type, []).append(handler)

        async def publish(self, event_type: str, payload: dict) -> None:
            for handler in self._handlers.get(event_type, []):
                await handler(payload)

    adapter = InMemoryStorageAdapter()
    bus = _FakeBus()
    runtime = SimpleNamespace(
        storage=adapter,
        event_bus=bus,
        _config=SimpleNamespace(plugins_dir=str(tmp_path)),
    )
    mod = SkillsModule(runtime)
    mod.context = SimpleNamespace(
        services=SimpleNamespace(register=AsyncMock(), unregister=AsyncMock()),
        http=MagicMock(),
    )
    await mod.register()

    await bus.publish(
        "internal.plugin.loaded",
        {
            "plugin_name": "evt",
            "plugin_version": "3.0.0",
            "skills": [{"name": "run", "intent": "run it"}],
        },
    )
    blob = await adapter.get(SKILLS_NAMESPACE, "evt")
    assert blob is not None
    assert blob["plugin_version"] == "3.0.0"

    await bus.publish("internal.plugin.unloaded", {"plugin_name": "evt"})
    assert await adapter.get(SKILLS_NAMESPACE, "evt") is None

    reg2 = SkillRegistry()
    assert await hydrate_registry_from_storage(reg2, runtime) == 0

    await mod.stop()


@pytest.mark.asyncio
async def test_start_migrates_disk_to_storage(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "disk_plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "name": "disk_plugin",
                "version": "1.0.0",
                "description": "d",
                "author": "a",
                "class_path": "plugins.disk.plugin.Plugin",
                "skills": [{"name": "a", "intent": "intent a"}],
            }
        ),
        encoding="utf-8",
    )

    adapter = InMemoryStorageAdapter()
    runtime = SimpleNamespace(
        storage=adapter,
        _config=SimpleNamespace(plugins_dir=str(tmp_path)),
        event_bus=None,
    )
    mod = SkillsModule(runtime)
    mod.context = SimpleNamespace(
        services=SimpleNamespace(register=AsyncMock(), unregister=AsyncMock()),
        http=MagicMock(),
    )
    await mod.register()
    await mod.start()

    blob = await adapter.get(SKILLS_NAMESPACE, "disk_plugin")
    assert blob is not None
    assert len(blob.get("skills") or []) == 1

    mod2 = SkillsModule(SimpleNamespace(storage=adapter, event_bus=None))
    mod2.registry = SkillRegistry()
    await hydrate_registry_from_storage(mod2.registry, runtime)
    assert mod2.registry.get("disk_plugin.a") is not None

    await mod.stop()
