from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from modules.admin.services.introspection import list_dashboard_cards


@pytest.mark.asyncio
async def test_list_dashboard_cards_from_manifests(tmp_path: Path):
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)
    for name, cards in (
        ("alpha", [{"id": "a1", "type": "metric", "service": "alpha.val"}]),
        ("beta", [{"id": "b1", "module": "./legacy.js"}]),
    ):
        d = plugins_dir / f"{name}_dir"
        d.mkdir(parents=True, exist_ok=True)
        (d / "plugin.json").write_text(
            json.dumps(
                {
                    "name": name,
                    "version": "1.0.0",
                    "description": "d",
                    "author": "t",
                    "class_path": f"plugins.{name}.plugin.P",
                    "ui": {"dashboard_cards": cards},
                }
            ),
            encoding="utf-8",
        )

    runtime = SimpleNamespace(_config=SimpleNamespace(plugins_dir=str(plugins_dir)))
    out = await list_dashboard_cards(runtime)
    assert out["total"] == 1
    assert out["items"][0]["plugin_name"] == "alpha"
    assert out["items"][0]["id"] == "a1"
    assert out["items"][0]["service"] == "alpha.val"
