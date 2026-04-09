from __future__ import annotations

from pathlib import Path

from scripts import validate_architecture_rules as architecture_rules


def test_scan_architecture_ignores_type_checking_imports(tmp_path: Path) -> None:
    core_dir = tmp_path / "core"
    modules_dir = tmp_path / "modules"
    plugins_dir = tmp_path / "plugins"
    core_dir.mkdir()
    modules_dir.mkdir()
    plugins_dir.mkdir()

    (core_dir / "runtime.py").write_text(
        "from modules.agent.module import AgentModule\n",
        encoding="utf-8",
    )
    (core_dir / "safe.py").write_text(
        "from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n    from modules.credentials.service import CredentialService\n",
        encoding="utf-8",
    )
    (modules_dir / "domain.py").write_text(
        "from core.credentials.domain import CredentialType\nfrom plugins.demo.plugin import DemoPlugin\n",
        encoding="utf-8",
    )
    (plugins_dir / "plugin.py").write_text("from core.runtime.config import Config\n", encoding="utf-8")

    report = architecture_rules.scan_architecture(tmp_path)

    assert len(report.core_to_modules) == 1
    assert report.core_to_modules[0].source == "core.runtime"
    assert report.core_to_modules[0].target == "modules.agent.module"

    assert len(report.modules_to_legacy_core) == 1
    assert report.modules_to_legacy_core[0].source == "modules.domain"
    assert report.modules_to_legacy_core[0].target == "core.credentials.domain"

    assert len(report.modules_to_plugins) == 1
    assert report.modules_to_plugins[0].source == "modules.domain"
    assert report.modules_to_plugins[0].target == "plugins.demo.plugin"


def test_main_enforce_fails_on_violations(tmp_path: Path) -> None:
    (tmp_path / "core").mkdir()
    (tmp_path / "modules").mkdir()
    (tmp_path / "plugins").mkdir()

    (tmp_path / "modules" / "x.py").write_text("from core.credentials.domain import CredentialType\n", encoding="utf-8")

    exit_code = architecture_rules.main(["--root", str(tmp_path), "--enforce"])

    assert exit_code == 1