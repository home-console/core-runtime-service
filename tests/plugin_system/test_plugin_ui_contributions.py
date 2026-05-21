from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.kernel.plugin_ui_contributions import ui_contributions_from_manifest
from modules.admin.services.introspection import get_plugin_ui_contributions


def test_ui_contributions_from_manifest_server_driven():
    manifest = {
        "version": "2.0.0",
        "ui": {
            "pages": [
                {
                    "path": "/plugins/x",
                    "type": "settings",
                    "config_schema": {"type": "object"},
                }
            ],
            "dashboard_cards": [
                {"id": "temp", "type": "metric", "service": "x.get_temp"},
            ],
        },
    }
    out = ui_contributions_from_manifest("x", manifest, loaded=True, on_disk=True)
    assert out["plugin_version"] == "2.0.0"
    assert out["pages"][0]["type"] == "settings"
    assert out["dashboard_cards"][0]["service"] == "x.get_temp"


@pytest.mark.asyncio
async def test_get_plugin_ui_contributions_from_disk(tmp_path: Path):
    plugins_dir = tmp_path / "plugins"
    plugin_dir = plugins_dir / "ui_demo_plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "name": "ui_demo",
                "version": "1.0.0",
                "description": "d",
                "author": "a",
                "class_path": "plugins.ui_demo.plugin.Plugin",
                "ui": {
                    "pages": [{"path": "/plugins/ui_demo", "type": "metric", "service": "ui_demo.val"}],
                },
            }
        ),
        encoding="utf-8",
    )

    pm = MagicMock()
    pm.get_plugin = AsyncMock(return_value=None)

    runtime = SimpleNamespace(
        _config=SimpleNamespace(plugins_dir=str(plugins_dir)),
        plugin_manager=pm,
    )

    out = await get_plugin_ui_contributions(runtime, "ui_demo")
    assert out is not None
    assert out["plugin_name"] == "ui_demo"
    assert out["pages"][0]["type"] == "metric"
    assert out["on_disk"] is True
    assert out["loaded"] is False
