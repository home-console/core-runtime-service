"""Admin-only service invoke allowlist for plugin UI metrics (§1.4 [1] B2)."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Set


def _collect_manifest_services(manifest: Optional[Dict[str, Any]]) -> Set[str]:
    names: Set[str] = set()
    if not manifest or not isinstance(manifest, dict):
        return names

    for svc in manifest.get("provides_services") or []:
        if isinstance(svc, str) and svc.strip():
            names.add(svc.strip())

    for skill in manifest.get("skills") or []:
        if isinstance(skill, dict):
            raw = skill.get("service")
            if isinstance(raw, str) and raw.strip():
                names.add(raw.strip())

    ui = manifest.get("ui")
    if isinstance(ui, dict):
        for page in ui.get("pages") or []:
            if isinstance(page, dict):
                raw = page.get("service")
                if isinstance(raw, str) and raw.strip():
                    names.add(raw.strip())
        for section in ("widgets", "dashboard_cards"):
            for item in ui.get(section) or []:
                if isinstance(item, dict):
                    raw = item.get("service")
                    if isinstance(raw, str) and raw.strip():
                        names.add(raw.strip())

    return names


def service_allowed_for_plugin_invoke(
    plugin_name: str,
    service_name: str,
    manifest: Optional[Dict[str, Any]],
) -> bool:
    """
    True if admin may invoke ``service_name`` on behalf of ``plugin_name``.

    - ``{plugin_name}.*`` prefix
    - listed in manifest provides_services / ui / skills
    """
    name = str(plugin_name or "").strip()
    svc = str(service_name or "").strip()
    if not name or not svc:
        return False
    if svc.startswith(f"{name}."):
        return True
    return svc in _collect_manifest_services(manifest)
