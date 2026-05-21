from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.skills.ingest import rehydrate_registry_from_disk
from modules.skills.registry import SkillRegistry


@pytest.mark.asyncio
async def test_rehydrate_registry_from_disk(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "demo_plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "name": "demo",
                "version": "2.1.0",
                "description": "d",
                "author": "a",
                "class_path": "plugins.demo.plugin.Plugin",
                "skills": [
                    {"name": "read", "intent": "read value"},
                    {"name": "write", "intent": "write value", "service": "demo.skill.write"},
                ],
            }
        ),
        encoding="utf-8",
    )
    empty_dir = tmp_path / "no_skills"
    empty_dir.mkdir()
    (empty_dir / "plugin.json").write_text(
        json.dumps(
            {
                "name": "empty",
                "version": "1.0.0",
                "description": "d",
                "author": "a",
                "class_path": "plugins.empty.plugin.Plugin",
            }
        ),
        encoding="utf-8",
    )

    runtime = SimpleNamespace(_config=SimpleNamespace(plugins_dir=str(tmp_path)))
    runtime.plugin_manager = MagicMock()

    reg = SkillRegistry()
    count = await rehydrate_registry_from_disk(reg, runtime)

    assert count == 1
    assert len(reg.list_skills()) == 2
    read_rec = reg.get("demo.read")
    assert read_rec is not None
    assert read_rec.plugin_version == "2.1.0"
    assert read_rec.service is None
    write_rec = reg.get("demo.write")
    assert write_rec is not None
    assert write_rec.service == "demo.skill.write"
    assert reg.get("empty.read") is None


@pytest.mark.asyncio
async def test_rehydrate_no_plugins_dir() -> None:
    runtime = SimpleNamespace(_config=SimpleNamespace(plugins_dir=None))
    reg = SkillRegistry()
    assert await rehydrate_registry_from_disk(reg, runtime) == 0
    assert reg.list_skills() == []
