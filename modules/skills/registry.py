"""In-memory registry of platform skills contributed by plugins."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional


@dataclass(frozen=True)
class SkillRecord:
    """A skill declared in plugin.json and registered at plugin load time."""

    id: str
    plugin_name: str
    name: str
    intent: str
    description: Optional[str]
    plugin_version: str
    service: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "plugin_name": self.plugin_name,
            "name": self.name,
            "intent": self.intent,
            "description": self.description,
            "plugin_version": self.plugin_version,
            "service": self.service,
        }


def skill_id(plugin_name: str, skill_name: str) -> str:
    return f"{plugin_name}.{skill_name}"


class SkillRegistry:
    """In-memory registry (runtime asyncio single-loop)."""

    def __init__(self) -> None:
        self._by_id: Dict[str, SkillRecord] = {}
        self._ids_by_plugin: Dict[str, set[str]] = {}

    def register_plugin_skills(
        self,
        plugin_name: str,
        plugin_version: str,
        skills: Iterable[dict[str, Any]],
    ) -> List[str]:
        """Replace skills for plugin. Returns registered skill ids."""
        self.unregister_plugin(plugin_name)
        registered: List[str] = []
        for item in skills:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            intent = str(item.get("intent", "")).strip()
            if not name or not intent:
                continue
            desc = item.get("description")
            description = (
                str(desc).strip() if isinstance(desc, str) and desc.strip() else None
            )
            svc_raw = item.get("service")
            service = (
                str(svc_raw).strip()
                if isinstance(svc_raw, str) and str(svc_raw).strip()
                else None
            )
            sid = skill_id(plugin_name, name)
            record = SkillRecord(
                id=sid,
                plugin_name=plugin_name,
                name=name,
                intent=intent,
                description=description,
                plugin_version=str(plugin_version or "0.0.0"),
                service=service,
            )
            self._by_id[sid] = record
            self._ids_by_plugin.setdefault(plugin_name, set()).add(sid)
            registered.append(sid)
        return registered

    def unregister_plugin(self, plugin_name: str) -> int:
        ids = self._ids_by_plugin.pop(plugin_name, set())
        for sid in ids:
            self._by_id.pop(sid, None)
        return len(ids)

    def get(self, skill_id_value: str) -> Optional[SkillRecord]:
        return self._by_id.get(skill_id_value)

    def list_skills(self, *, plugin_name: Optional[str] = None) -> List[SkillRecord]:
        if plugin_name is None:
            return sorted(self._by_id.values(), key=lambda r: r.id)
        ids = self._ids_by_plugin.get(plugin_name, set())
        return sorted(
            (self._by_id[sid] for sid in ids if sid in self._by_id),
            key=lambda r: r.id,
        )
