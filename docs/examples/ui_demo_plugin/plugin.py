"""Server-driven UI reference plugin — copy to plugins/ for local dev."""

from __future__ import annotations

import time
from typing import Any

from sdk.config import register_ui_config_services
from sdk.plugin_ext import BasePlugin, PluginMetadata


class UiDemoPlugin(BasePlugin):
    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="ui_demo",
            version="1.0.0",
            description="Server-driven UI demo",
            author="Home Console",
        )

    async def on_load(self) -> None:
        await register_ui_config_services(self)

        async def get_metric(_payload: object = None) -> dict[str, Any]:
            cfg = await self.storage.get("ui_config") if self.storage else {}
            label = "demo"
            if isinstance(cfg, dict) and isinstance(cfg.get("label"), str):
                label = cfg["label"]
            return {
                "value": round(time.time() % 100, 2),
                "unit": "°C",
                "label": label,
                "enabled": bool(cfg.get("enabled")) if isinstance(cfg, dict) else True,
            }

        await self.register_service("ui_demo.get_metric", get_metric, admin_only=True)

    async def on_start(self) -> None:
        return None

    async def on_stop(self) -> None:
        return None

    async def on_unload(self) -> None:
        return None
