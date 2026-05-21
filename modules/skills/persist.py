"""SK5: persist skill registry in core runtime storage across restarts."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterable, List, Optional

from modules.skills.ingest import plugins_dir_for_runtime, skills_from_manifest
from modules.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)

SKILLS_NAMESPACE = "skills"
SKILLS_INDEX_KEY = "_index"


def _runtime_storage(runtime: Any) -> Any | None:
    return getattr(runtime, "storage", None)


def _normalize_skill_dict(item: dict[str, Any]) -> Optional[dict[str, Any]]:
    name = str(item.get("name", "")).strip()
    intent = str(item.get("intent", "")).strip()
    if not name or not intent:
        return None
    out: dict[str, Any] = {"name": name, "intent": intent}
    desc = item.get("description")
    if isinstance(desc, str) and desc.strip():
        out["description"] = desc.strip()
    svc = item.get("service")
    if isinstance(svc, str) and svc.strip():
        out["service"] = svc.strip()
    return out


def normalize_skills_for_storage(skills: Iterable[dict[str, Any]]) -> List[dict[str, Any]]:
    normalized: List[dict[str, Any]] = []
    for item in skills:
        if not isinstance(item, dict):
            continue
        row = _normalize_skill_dict(item)
        if row is not None:
            normalized.append(row)
    return normalized


def _plugin_blob(plugin_name: str, plugin_version: str, skills: List[dict[str, Any]]) -> dict[str, Any]:
    return {
        "plugin_name": plugin_name,
        "plugin_version": str(plugin_version or "0.0.0"),
        "skills": skills,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


async def _read_index(storage: Any) -> List[str]:
    raw = await storage.get(SKILLS_NAMESPACE, SKILLS_INDEX_KEY)
    if not isinstance(raw, dict):
        return []
    plugins = raw.get("plugins")
    if not isinstance(plugins, list):
        return []
    return sorted({str(p).strip() for p in plugins if str(p).strip()})


async def _write_index(storage: Any, plugin_names: Iterable[str]) -> None:
    await storage.set(
        SKILLS_NAMESPACE,
        SKILLS_INDEX_KEY,
        {"plugins": sorted({str(p).strip() for p in plugin_names if str(p).strip()})},
    )


async def persist_plugin_skills(
    runtime: Any,
    plugin_name: str,
    plugin_version: str,
    skills: Iterable[dict[str, Any]],
) -> bool:
    """Write one plugin's skills snapshot to runtime storage."""
    storage = _runtime_storage(runtime)
    if storage is None:
        return False

    name = str(plugin_name or "").strip()
    if not name:
        return False

    normalized = normalize_skills_for_storage(skills)
    if not normalized:
        await delete_plugin_skills(runtime, name)
        return False

    await storage.set(
        SKILLS_NAMESPACE,
        name,
        _plugin_blob(name, plugin_version, normalized),
    )
    index = await _read_index(storage)
    if name not in index:
        index.append(name)
    await _write_index(storage, index)
    return True


async def delete_plugin_skills(runtime: Any, plugin_name: str) -> bool:
    storage = _runtime_storage(runtime)
    if storage is None:
        return False

    name = str(plugin_name or "").strip()
    if not name:
        return False

    await storage.delete(SKILLS_NAMESPACE, name)
    index = await _read_index(storage)
    if name in index:
        index = [p for p in index if p != name]
        await _write_index(storage, index)
    return True


async def hydrate_registry_from_storage(registry: SkillRegistry, runtime: Any) -> int:
    """
    Load SkillRegistry from persisted storage (SK5 full).

    Returns number of plugins that contributed at least one skill.
    """
    storage = _runtime_storage(runtime)
    if storage is None:
        return 0

    plugin_names = await _read_index(storage)
    if not plugin_names:
        keys = await storage.list_keys(SKILLS_NAMESPACE)
        plugin_names = sorted(
            k for k in keys if k and not k.startswith("_")
        )

    loaded_plugins = 0
    total_skills = 0
    for plugin_name in plugin_names:
        blob = await storage.get(SKILLS_NAMESPACE, plugin_name)
        if not isinstance(blob, dict):
            continue
        skills_raw = blob.get("skills")
        if not isinstance(skills_raw, list):
            continue
        version = str(blob.get("plugin_version") or "0.0.0")
        ids = registry.register_plugin_skills(plugin_name, version, skills_raw)
        if ids:
            loaded_plugins += 1
            total_skills += len(ids)

    if loaded_plugins:
        logger.info(
            "skills: hydrated from storage — %s plugin(s), %s skill(s)",
            loaded_plugins,
            total_skills,
        )
    return loaded_plugins


async def snapshot_registry_to_storage(registry: SkillRegistry, runtime: Any) -> int:
    """Persist all in-memory registry entries (e.g. after SK5-lite disk bootstrap)."""
    by_plugin: dict[str, list] = {}
    for record in registry.list_skills():
        by_plugin.setdefault(record.plugin_name, []).append(record)

    written = 0
    for plugin_name, records in by_plugin.items():
        if not records:
            continue
        skills = [
            {
                "name": r.name,
                "intent": r.intent,
                **({"description": r.description} if r.description else {}),
                **({"service": r.service} if r.service else {}),
            }
            for r in records
        ]
        version = records[0].plugin_version
        if await persist_plugin_skills(runtime, plugin_name, version, skills):
            written += 1
    return written


async def reconcile_registry_with_disk(registry: SkillRegistry, runtime: Any) -> int:
    """
    Refresh registry from plugin.json on disk when version differs or plugin is new.

    Removes skills for plugins that are no longer present under plugins_dir.
    """
    from core.kernel.plugin_loader import PluginManifestLoader

    plugins_dir = plugins_dir_for_runtime(runtime)
    if plugins_dir is None:
        return 0

    manifests = await PluginManifestLoader.discover_manifests(plugins_dir, runtime)
    disk_plugins = set(manifests.keys())
    updated = 0

    for plugin_name, manifest in manifests.items():
        skills = skills_from_manifest(manifest)
        if not skills:
            continue
        version = str(manifest.get("version") or "0.0.0")
        existing = registry.list_skills(plugin_name=plugin_name)
        if (
            existing
            and existing[0].plugin_version == version
            and len(existing) == len(normalize_skills_for_storage(skills))
        ):
            continue
        registry.register_plugin_skills(plugin_name, version, skills)
        await persist_plugin_skills(runtime, plugin_name, version, skills)
        updated += 1

    for plugin_name in registry.list_plugin_names():
        if plugin_name in disk_plugins:
            continue
        if PluginManifestLoader.find_plugin_directory(plugins_dir, plugin_name) is not None:
            continue
        registry.unregister_plugin(plugin_name)
        await delete_plugin_skills(runtime, plugin_name)
        updated += 1
        logger.info("skills: removed orphan plugin %s (not on disk)", plugin_name)

    return updated
