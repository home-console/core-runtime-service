"""Auth service facade for modules layer."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path


def _find_plugin_app_dir(repo_root: Path, required_rel_file: Path) -> Path:
    plugins_dir = repo_root / "plugins"
    candidates: list[Path] = []
    if plugins_dir.exists():
        for p in sorted(plugins_dir.iterdir(), key=lambda x: x.name):
            if not p.is_dir():
                continue
            app_dir = p / "app"
            if (app_dir / required_rel_file).exists():
                candidates.append(app_dir)
    if not candidates:
        raise ImportError(
            f"Cannot find plugin app dir providing {required_rel_file.as_posix()} under plugins/*/app"
        )
    # Deterministic: prefer lexicographically first match.
    return candidates[0]


def _load_auth_service():
    repo_root = Path(__file__).resolve().parents[2]
    plugin_app_dir = _find_plugin_app_dir(
        repo_root, Path("core") / "security" / "auth_service.py"
    )

    app_pkg = import_module("app")
    app_path = getattr(app_pkg, "__path__", None)
    if app_path is not None and str(plugin_app_dir) not in app_path:
        app_path.append(str(plugin_app_dir))

    module = import_module("app.core.security.auth_service")
    return module.AuthService


AuthService = _load_auth_service()

__all__ = ["AuthService"]