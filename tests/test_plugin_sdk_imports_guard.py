from __future__ import annotations

from pathlib import Path

from scripts import validate_plugin_sdk_imports


def test_plugin_sdk_imports_guard_passes_in_repo_root() -> None:
    root = Path(__file__).resolve().parents[1]
    assert validate_plugin_sdk_imports.main(["--root", str(root), "--enforce"]) == 0


def test_plugin_sdk_imports_allows_local_app_package(tmp_path: Path) -> None:
    """
    У некоторых плагинов есть локальный пакет `app/` (например client-manager-plugin).
    Импорт `from app.config import ...` в таком случае НЕ должен считаться import'ом project-level `app/`.
    """
    (tmp_path / "plugins").mkdir()
    plugin_dir = tmp_path / "plugins" / "demo_plugin"
    plugin_dir.mkdir(parents=True)

    # локальный пакет плагина
    (plugin_dir / "app").mkdir()
    (plugin_dir / "app" / "__init__.py").write_text("", encoding="utf-8")
    (plugin_dir / "app" / "config.py").write_text("X = 1\n", encoding="utf-8")

    (plugin_dir / "plugin.py").write_text(
        "from app.config import X\n\nVALUE = X\n",
        encoding="utf-8",
    )

    assert validate_plugin_sdk_imports.main(["--root", str(tmp_path), "--enforce"]) == 0


def test_plugin_sdk_imports_forbids_core_import(tmp_path: Path) -> None:
    (tmp_path / "plugins").mkdir()
    plugin_dir = tmp_path / "plugins" / "bad_plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.py").write_text(
        "from core.runtime.runtime import CoreRuntime\n",
        encoding="utf-8",
    )
    assert validate_plugin_sdk_imports.main(["--root", str(tmp_path), "--enforce"]) == 1

