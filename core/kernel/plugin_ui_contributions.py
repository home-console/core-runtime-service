"""Normalize plugin.json ``ui`` section for inspector / server-driven UI."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _page_dto(item: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"path": str(item.get("path", ""))}
    for key in ("type", "module", "title", "service", "config", "config_schema"):
        if key in item and item[key] is not None:
            out[key] = item[key]
    return out


def _widget_dto(item: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"id": str(item.get("id", ""))}
    for key in ("type", "module", "title", "service", "config", "config_schema"):
        if key in item and item[key] is not None:
            out[key] = item[key]
    return out


def ui_contributions_from_manifest(
    plugin_name: str,
    manifest: Optional[Dict[str, Any]],
    *,
    loaded: bool = False,
    on_disk: bool = False,
) -> Dict[str, Any]:
    """Build payload for PluginUiContributionsDto."""
    version = None
    pages: List[Dict[str, Any]] = []
    widgets: List[Dict[str, Any]] = []
    cards: List[Dict[str, Any]] = []

    if manifest and isinstance(manifest, dict):
        version = str(manifest.get("version") or "") or None
        ui = manifest.get("ui")
        if isinstance(ui, dict):
            for p in ui.get("pages") or []:
                if isinstance(p, dict):
                    pages.append(_page_dto(p))
            for w in ui.get("widgets") or []:
                if isinstance(w, dict):
                    widgets.append(_widget_dto(w))
            for c in ui.get("dashboard_cards") or []:
                if isinstance(c, dict):
                    cards.append(_widget_dto(c))

    return {
        "plugin_name": plugin_name,
        "plugin_version": version,
        "on_disk": on_disk,
        "loaded": loaded,
        "pages": pages,
        "widgets": widgets,
        "dashboard_cards": cards,
    }
