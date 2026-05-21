"""
E2e smoke for [2] API-only skills path (new-tasks 2.5).

Pipeline: manifest with skills → on-disk install (plugins dir) → rehydrate →
GET skills.list → plugin loaded event → skill still listed.
Publish step covered in marketplace-api/tests/test_skills_publish_pipeline.py.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.skills.ingest import rehydrate_registry_from_disk
from modules.skills.module import SkillsModule


class _FakeBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list] = {}

    async def subscribe(self, event_type: str, handler) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    async def publish(self, event_type: str, payload: dict) -> None:
        for handler in self._handlers.get(event_type, []):
            await handler(payload)


def _write_installed_plugin(plugins_dir: Path, *, name: str = "e2e_skills_plugin") -> None:
    """Simulate hc install extracting plugin into plugins_dir."""
    plugin_dir = plugins_dir / name
    plugin_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": name,
        "version": "1.0.0",
        "description": "E2E skills pipeline fixture",
        "author": "Home Console Tests",
        "class_path": f"plugins.{name}.plugin.Plugin",
        "skills": [
            {
                "name": "ping",
                "intent": "health check",
                "service": f"{name}.skill.ping",
            }
        ],
    }
    (plugin_dir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    (plugin_dir / "plugin.py").write_text("# fixture\n", encoding="utf-8")


@pytest.mark.asyncio
async def test_skills_pipeline_disk_rehydrate_and_load(tmp_path: Path) -> None:
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    _write_installed_plugin(plugins_dir)

    runtime = SimpleNamespace(
        _config=SimpleNamespace(plugins_dir=str(plugins_dir)),
        event_bus=_FakeBus(),
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
    assert listed["items"][0]["id"] == "e2e_skills_plugin.ping"
    assert listed["items"][0]["service"] == "e2e_skills_plugin.skill.ping"

    await runtime.event_bus.publish(
        "internal.plugin.loaded",
        {
            "plugin_name": "e2e_skills_plugin",
            "plugin_version": "1.1.0",
            "skills": [{"name": "ping", "intent": "health check", "service": "e2e_skills_plugin.skill.ping"}],
        },
    )

    listed2 = await mod._service_list(plugin="e2e_skills_plugin")
    assert listed2["total"] == 1
    assert listed2["items"][0]["plugin_version"] == "1.1.0"

    got = await mod._service_get("e2e_skills_plugin.ping")
    assert got["name"] == "ping"

    await mod.stop()


@pytest.mark.asyncio
async def test_rehydrate_after_simulated_core_restart(tmp_path: Path) -> None:
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    _write_installed_plugin(plugins_dir)

    runtime = SimpleNamespace(_config=SimpleNamespace(plugins_dir=str(plugins_dir)))
    from modules.skills.registry import SkillRegistry

    reg = SkillRegistry()
    n = await rehydrate_registry_from_disk(reg, runtime)
    assert n == 1
    assert reg.get("e2e_skills_plugin.ping") is not None

    reg2 = SkillRegistry()
    n2 = await rehydrate_registry_from_disk(reg2, runtime)
    assert n2 == 1
    assert len(reg2.list_skills()) == 1


def test_marketplace_zip_with_skills_validates(tmp_path: Path) -> None:
    """Same manifest shape as publish archive (skills only, API-only)."""
    from core.kernel.plugin_manifest_schema import validate_plugin_json

    manifest = {
        "name": "pub_skills",
        "version": "1.0.0",
        "description": "Publish fixture",
        "author": "Tests",
        "class_path": "plugins.pub_skills.plugin.Plugin",
        "skills": [{"name": "snap", "intent": "snapshot"}],
    }
    m = validate_plugin_json(manifest)
    assert m["skills"][0]["name"] == "snap"

    zpath = tmp_path / "plugin.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("plugin.json", json.dumps(manifest))
        zf.writestr("plugin.py", "# x")
    with zipfile.ZipFile(zpath) as zf:
        raw = json.loads(zf.read("plugin.json"))
    assert raw["skills"][0]["intent"] == "snapshot"
