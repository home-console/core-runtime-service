"""Load plugin.json skills for lifecycle / event handlers."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.kernel.plugin_loader import PluginManifestLoader

logger = logging.getLogger(__name__)


def skills_from_manifest(manifest: Optional[Dict[str, Any]]) -> List[dict[str, Any]]:
    if not manifest or not isinstance(manifest, dict):
        return []
    raw = manifest.get("skills")
    if not isinstance(raw, list):
        return []
    return [s for s in raw if isinstance(s, dict)]


def plugins_dir_for_runtime(runtime: Any) -> Optional[Path]:
    """Resolved plugins directory from runtime config."""
    config = getattr(runtime, "_config", None) or getattr(runtime, "config", None)
    plugins_dir_str = getattr(config, "plugins_dir", None) if config is not None else None
    if not plugins_dir_str:
        return None
    plugins_dir = Path(str(plugins_dir_str)).expanduser()
    if not plugins_dir.is_dir():
        return None
    return plugins_dir


def load_manifest_for_plugin(runtime: Any, plugin_name: str) -> Optional[Dict[str, Any]]:
    """Read plugin.json for an installed plugin directory."""
    config = getattr(runtime, "_config", None) or getattr(runtime, "config", None)
    plugins_dir = plugins_dir_for_runtime(runtime)
    if plugins_dir is None:
        return None
    plugin_dir = PluginManifestLoader.find_plugin_directory(plugins_dir, plugin_name)
    if plugin_dir is None:
        return None
    return PluginManifestLoader.load_manifest(plugin_dir, strict=False)


async def rehydrate_registry_from_disk(registry: Any, runtime: Any) -> int:
    """
    SK5-lite: fill SkillRegistry from plugin.json on disk at module start.

    Does not require plugins to be loaded/started. Later ``internal.plugin.loaded``
    may refresh entries for running plugins.
    Returns number of plugins that contributed at least one skill.
    """
    plugins_dir = plugins_dir_for_runtime(runtime)
    if plugins_dir is None:
        return 0

    manifests = await PluginManifestLoader.discover_manifests(plugins_dir, runtime)
    registered_plugins = 0
    total_skills = 0
    for plugin_name, manifest in manifests.items():
        skills = skills_from_manifest(manifest)
        if not skills:
            continue
        version = str(manifest.get("version") or "0.0.0")
        ids = registry.register_plugin_skills(plugin_name, version, skills)
        if ids:
            registered_plugins += 1
            total_skills += len(ids)

    if registered_plugins:
        logger.info(
            "skills: rehydrated from disk — %s plugin(s), %s skill(s)",
            registered_plugins,
            total_skills,
        )
    return registered_plugins
