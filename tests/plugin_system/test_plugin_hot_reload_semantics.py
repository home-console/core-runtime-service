import importlib
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from core.runtime.runtime import CoreRuntime


def _write_plugin(plugin_dir: Path, plugin_name: str) -> None:
    # Minimal plugin implementation
    (plugin_dir / "plugin.py").write_text(
        """
from core.kernel.base_plugin import BasePlugin


class TestPlugin(BasePlugin):
    @property
    def metadata(self):
        from core.kernel.base_plugin import PluginMetadata
        return PluginMetadata(name="PLUGIN_NAME", version="1.0.0")

    async def on_start(self) -> None:
        await super().on_start()
    """.replace("PLUGIN_NAME", plugin_name),
        encoding="utf-8",
    )

    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "name": plugin_name,
                "version": "1.0.0",
                "class_path": "plugin.TestPlugin",
                "description": "hot reload semantics test",
                "author": "test",
                "dependencies": [],
                "allowed_services": [],
                "is_integration": False,
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_reload_plugin_does_not_call_importlib_reload(memory_adapter, monkeypatch):
    runtime = CoreRuntime(memory_adapter)

    with tempfile.TemporaryDirectory() as tmp:
        plugins_dir = Path(tmp)
        runtime._config = type("Cfg", (), {"plugins_dir": str(plugins_dir)})()

        plugin_name = "hot_reload_test_plugin"
        plugin_dir = plugins_dir / plugin_name
        plugin_dir.mkdir()
        _write_plugin(plugin_dir, plugin_name)

        # Load once so the plugin exists in registry
        assert await runtime.plugin_manager.load_plugin_by_name(
            plugin_name, plugins_dir=plugins_dir
        )

        # If lifecycle.reload_plugin calls importlib.reload, we fail the test.
        reload_mock = Mock(wraps=importlib.reload)
        monkeypatch.setattr(importlib, "reload", reload_mock)

        await runtime.plugin_manager.reload_plugin(plugin_name)

        assert reload_mock.call_count == 0

