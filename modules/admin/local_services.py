from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


def create_marketplace_catalog_handler(*, repo_root: Path) -> Callable[..., Awaitable[list[dict[str, Any]]]]:
    """
    App/admin-facing marketplace catalog builder.

    Source of truth: `plugins/*/plugin.json` manifests in the repo checkout.
    """

    async def handler(*_args: Any, **_kw: Any) -> list[dict[str, Any]]:
        try:
            plugins_dir = repo_root / "plugins"
            catalog: list[dict[str, Any]] = []

            if not plugins_dir.exists():
                return catalog

            for entry in sorted(plugins_dir.iterdir(), key=lambda p: p.name):
                if not entry.is_dir():
                    continue
                manifest_path = entry / "plugin.json"
                if not manifest_path.exists():
                    continue

                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                except Exception:
                    logger.debug(
                        "marketplace_catalog: error processing item (skipping)",
                        exc_info=True,
                    )
                    continue

                plugin_id = manifest.get("name") or entry.name
                display_name = (
                    manifest.get("integration_name")
                    or manifest.get("name")
                    or entry.name
                )
                catalog_item: dict[str, Any] = {
                    "id": plugin_id,
                    "name": display_name,
                    "description": manifest.get("description", ""),
                    "version": manifest.get("version"),
                }

                deps = manifest.get("dependencies")
                if isinstance(deps, list) and deps:
                    catalog_item["dependencies"] = deps

                catalog.append(catalog_item)

            return catalog
        except Exception as e:
            logger.warning("marketplace catalog build failed: %s", e, exc_info=True)
            return []

    return handler


async def webhook_test_service(payload: Any = None, **_kwargs: Any) -> dict[str, Any]:
    logger.info("[Webhook Demo] Received payload: %r", payload)
    return {
        "ok": True,
        "message": "Webhook received and processed",
        "payload_type": str(type(payload).__name__),
        "payload_sample": str(payload)[:100] if payload else None,
    }

