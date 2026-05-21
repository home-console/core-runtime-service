from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.kernel.plugin_admin_invoke import service_allowed_for_plugin_invoke
from modules.admin.services.introspection import (
    get_plugin_ui_config,
    invoke_plugin_service,
    set_plugin_ui_config,
)


def test_service_allowed_for_plugin_invoke():
    manifest = {
        "provides_services": ["ui_demo.get_metric"],
        "ui": {"pages": [{"path": "/x", "type": "metric", "service": "ui_demo.get_metric"}]},
        "skills": [{"name": "p", "intent": "i", "service": "ui_demo.get_metric"}],
    }
    assert service_allowed_for_plugin_invoke("ui_demo", "ui_demo.get_metric", manifest)
    assert service_allowed_for_plugin_invoke("ui_demo", "ui_demo.other", manifest)
    assert not service_allowed_for_plugin_invoke("ui_demo", "other.get_metric", manifest)


@pytest.mark.asyncio
async def test_plugin_config_roundtrip(tmp_path: Path):
    plugins_dir = tmp_path / "plugins"
    plugin_dir = plugins_dir / "cfg_demo"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "name": "cfg_demo",
                "version": "1.0.0",
                "description": "d",
                "author": "a",
                "class_path": "plugins.cfg_demo.plugin.Plugin",
            }
        ),
        encoding="utf-8",
    )

    storage = MagicMock()
    store: dict = {}

    async def _get(ns, key):
        return store.get(f"{ns}:{key}")

    async def _set(ns, key, val):
        store[f"{ns}:{key}"] = val

    storage.get = AsyncMock(side_effect=_get)
    storage.set = AsyncMock(side_effect=_set)

    runtime = SimpleNamespace(
        _config=SimpleNamespace(plugins_dir=str(plugins_dir)),
        plugin_manager=MagicMock(get_plugin=AsyncMock(return_value=None)),
        storage=storage,
        service_registry=MagicMock(),
    )

    empty = await get_plugin_ui_config(runtime, "cfg_demo")
    assert empty["config"] == {}

    saved = await set_plugin_ui_config(runtime, "cfg_demo", config={"enabled": True, "label": "X"})
    assert saved["config"]["label"] == "X"

    loaded = await get_plugin_ui_config(runtime, "cfg_demo")
    assert loaded["config"]["enabled"] is True


@pytest.mark.asyncio
async def test_invoke_plugin_service_allowlist(monkeypatch: pytest.MonkeyPatch):
    registry = MagicMock()
    registry.has_service = AsyncMock(return_value=True)
    registry.call = AsyncMock(return_value={"value": 42})

    runtime = SimpleNamespace(
        _config=SimpleNamespace(plugins_dir=None),
        storage=MagicMock(),
        service_registry=registry,
        plugin_manager=MagicMock(get_plugin=AsyncMock(return_value=True)),
    )

    manifest = {"provides_services": ["p.metric"]}

    async def _load(_rt, _name):
        return manifest, True

    monkeypatch.setattr(
        "modules.admin.services.introspection._load_plugin_manifest",
        _load,
    )
    out = await invoke_plugin_service(runtime, "p", service="p.metric", kwargs={})
    assert out["ok"] is True
    assert out["result"]["value"] == 42
