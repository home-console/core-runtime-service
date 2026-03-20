from __future__ import annotations

from pathlib import Path

from scripts import validate_architecture_rules as architecture_rules


def test_core_to_modules_imports_are_reported(tmp_path: Path) -> None:
    core_dir = tmp_path / "core"
    core_dir.mkdir()

    (core_dir / "runtime.py").write_text(
        "from modules.agent.module import AgentModule\n",
        encoding="utf-8",
    )

    report = architecture_rules.scan_architecture(tmp_path)

    assert len(report.core_to_modules) == 1
    assert report.core_to_modules[0].source == "core.runtime"
    assert report.core_to_modules[0].target == "modules.agent.module"


def test_plugins_to_modules_imports_are_reported(tmp_path: Path) -> None:
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()

    (plugins_dir / "plugin.py").write_text(
        "from modules.operations.handlers import handle_oauth_refresh\n",
        encoding="utf-8",
    )

    report = architecture_rules.scan_architecture(tmp_path)

    assert len(report.plugins_to_modules) == 1
    assert report.plugins_to_modules[0].source == "plugins.plugin"
    assert report.plugins_to_modules[0].target == "modules.operations.handlers"