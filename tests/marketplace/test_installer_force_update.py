"""Проверка force_update в MarketplaceInstaller."""

from __future__ import annotations

import json
import tempfile
import zipfile
from pathlib import Path

import pytest

from modules.marketplace.installer import MarketplaceInstaller


def _zip_plugin(root: Path, *, description: str) -> Path:
    manifest = {
        "name": "fu_plugin",
        "version": "0.1.0",
        "description": description,
        "author": "test",
        "class_path": "plugin.FUPlugin",
    }
    plugin_py = """
from core.kernel.base_plugin import BasePlugin, PluginMetadata

class FUPlugin(BasePlugin):
    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="fu_plugin",
            version="0.1.0",
            description="fu",
            author="test",
        )
""".lstrip()
    (root / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / "plugin.py").write_text(plugin_py, encoding="utf-8")
    zpath = root / "p.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.write(root / "plugin.json", "plugin.json")
        zf.write(root / "plugin.py", "plugin.py")
    return zpath


@pytest.mark.asyncio
async def test_install_from_file_force_update_replaces_directory(tmp_path: Path) -> None:
    plugins_dir = tmp_path / "plugins"
    installer = MarketplaceInstaller(plugins_dir)

    with tempfile.TemporaryDirectory() as td:
        z1 = _zip_plugin(Path(td), description="first")
        r1 = await installer.install_from_file(z1)
        assert r1["name"] == "fu_plugin"
        assert (plugins_dir / "fu_plugin" / "plugin.json").read_text(encoding="utf-8")

    with tempfile.TemporaryDirectory() as td2:
        z2 = _zip_plugin(Path(td2), description="second")
        r2 = await installer.install_from_file(z2, force_update=True)
        assert r2["name"] == "fu_plugin"
        data = json.loads((plugins_dir / "fu_plugin" / "plugin.json").read_text(encoding="utf-8"))
        assert data["description"] == "second"
