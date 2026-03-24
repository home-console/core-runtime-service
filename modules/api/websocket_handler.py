"""WebSocket handler facade for modules layer."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path


def _load_websocket_handler():
    repo_root = Path(__file__).resolve().parents[2]
    plugin_app_dir = repo_root / "plugins" / "client-manager-service" / "app"

    app_pkg = import_module("app")
    app_path = getattr(app_pkg, "__path__", None)
    if app_path is not None and str(plugin_app_dir) not in app_path:
        app_path.append(str(plugin_app_dir))

    module = import_module("app.core.websocket_handler")
    return module.WebSocketHandler


WebSocketHandler = _load_websocket_handler()

__all__ = ["WebSocketHandler"]
