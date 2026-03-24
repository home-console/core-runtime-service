"""Auth service facade for modules layer."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path


def _load_auth_service():
    repo_root = Path(__file__).resolve().parents[2]
    plugin_app_dir = repo_root / "plugins" / "client-manager-service" / "app"

    app_pkg = import_module("app")
    app_path = getattr(app_pkg, "__path__", None)
    if app_path is not None and str(plugin_app_dir) not in app_path:
        app_path.append(str(plugin_app_dir))

    module = import_module("app.core.security.auth_service")
    return module.AuthService


AuthService = _load_auth_service()

__all__ = ["AuthService"]