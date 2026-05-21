"""
Register ``{plugin}.config.get`` / ``{plugin}.config.set`` for server-driven settings UI.

Storage key: ``ui_config`` in the plugin namespace (see core.kernel.plugin_ui_config).
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from core.kernel.plugin_ui_config import PLUGIN_UI_CONFIG_KEY

ConfigHandler = Callable[..., Awaitable[Any]]


async def register_ui_config_services(plugin: Any) -> None:
    """
    Register admin-only config services on a loaded plugin instance.

    Requires ``plugin.storage`` (StorageProxy) and ``register_service``.
    """
    storage = getattr(plugin, "storage", None)
    register = getattr(plugin, "register_service", None)
    meta = getattr(plugin, "metadata", None)
    if storage is None or register is None or meta is None:
        return

    plugin_name = str(getattr(meta, "name", "") or "").strip()
    if not plugin_name:
        return

    async def config_get(_payload: object = None) -> dict[str, Any]:
        val = await storage.get(PLUGIN_UI_CONFIG_KEY)
        if isinstance(val, dict):
            return val
        return {}

    async def config_set(payload: object = None, **kwargs: Any) -> dict[str, bool]:
        body: dict[str, Any] = {}
        if isinstance(payload, dict):
            body = payload
        elif kwargs:
            body = dict(kwargs)
        cfg = body.get("config", body)
        if not isinstance(cfg, dict):
            cfg = {}
        await storage.put(PLUGIN_UI_CONFIG_KEY, cfg)
        return {"ok": True}

    await register(f"{plugin_name}.config.get", config_get, admin_only=True)
    await register(f"{plugin_name}.config.set", config_set, admin_only=True)
