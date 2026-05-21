"""SK7: invoke skill handlers on plugin via dotted path when not in service registry."""

from __future__ import annotations

import inspect
import logging
from typing import Any, Callable, Dict, Optional

from core.kernel.plugin_admin_invoke import service_allowed_for_plugin_invoke
from core.kernel.plugin_registry import PluginState
from modules.skills.ingest import load_manifest_for_plugin
from modules.skills.registry import SkillRecord

logger = logging.getLogger(__name__)


def _plugin_manager(runtime: Any) -> Any | None:
    pm = getattr(runtime, "plugin_manager", None)
    if pm is not None:
        return pm
    plugins = getattr(runtime, "plugins", None)
    return getattr(plugins, "plugin_manager", None) if plugins else None


def _path_after_prefix(plugin_name: str, service_name: str) -> Optional[str]:
    prefix = f"{plugin_name}."
    svc = str(service_name or "").strip()
    if not svc.startswith(prefix):
        return None
    return svc[len(prefix) :].strip() or None


def _resolve_callable(root: Any, path: str) -> Callable[..., Any]:
    parts = [p for p in path.split(".") if p]
    if not parts or any(p.startswith("_") for p in parts):
        raise AttributeError(path)
    obj: Any = root
    for part in parts:
        obj = getattr(obj, part)
    if not callable(obj):
        raise TypeError(path)
    return obj


async def _call(handler: Callable[..., Any], params: Dict[str, Any]) -> Any:
    if inspect.iscoroutinefunction(handler):
        return await handler(**params)
    out = handler(**params)
    return await out if inspect.isawaitable(out) else out


async def _load_manifest(runtime: Any, plugin_name: str) -> Optional[Dict[str, Any]]:
    manifest = load_manifest_for_plugin(runtime, plugin_name)
    if manifest is not None:
        return manifest
    pm = _plugin_manager(runtime)
    plugin = pm.get_plugin(plugin_name) if pm is not None else None
    meta = getattr(plugin, "metadata", None) if plugin is not None else None
    if meta is None:
        return None
    return {
        "name": getattr(meta, "name", plugin_name),
        "version": getattr(meta, "version", "0.0.0"),
        "skills": getattr(meta, "skills", None),
        "provides_services": getattr(meta, "provides_services", None),
        "ui": getattr(meta, "ui", None),
    }


async def invoke_via_plugin_dotted_path(
    runtime: Any,
    record: SkillRecord,
    service_name: str,
    params: Dict[str, Any],
) -> tuple[bool, Any, Optional[str]]:
    pm = _plugin_manager(runtime)
    if pm is None:
        return False, "plugin manager unavailable", "invoke_not_configured"

    plugin = pm.get_plugin(record.plugin_name)
    if plugin is None:
        return False, "plugin not loaded", "plugin_not_loaded"

    state = pm.get_plugin_state(record.plugin_name)
    if inspect.isawaitable(state):
        state = await state
    if state != PluginState.STARTED:
        state_val = state.value if state is not None else "unknown"
        return False, f"plugin not started (state={state_val})", "plugin_not_started"

    manifest = await _load_manifest(runtime, record.plugin_name)
    if not service_allowed_for_plugin_invoke(record.plugin_name, service_name, manifest):
        return False, "service not allowed for plugin", "forbidden_service"

    rel = _path_after_prefix(record.plugin_name, service_name)
    if not rel:
        return False, "invalid service name", "forbidden_service"

    handler: Callable[..., Any] | None = None
    for candidate in (rel, rel.replace(".", "_")):
        try:
            handler = _resolve_callable(plugin, candidate)
            break
        except (AttributeError, TypeError):
            continue
    if handler is None:
        return False, "invoke not configured", "invoke_not_configured"

    try:
        return True, await _call(handler, params), None
    except Exception as exc:
        logger.warning("skills dotted invoke %s failed", service_name, exc_info=True)
        return False, str(exc), "invoke_failed"


async def invoke_skill(
    runtime: Any,
    record: SkillRecord,
    service_name: str,
    params: Dict[str, Any],
) -> tuple[bool, Any, str, Optional[str]]:
    reg = getattr(runtime, "service_registry", None)
    if reg is not None and await reg.has_service(service_name):
        try:
            return True, await reg.call(service_name, **params), service_name, None
        except Exception as exc:
            logger.warning("skills.invoke failed for %s via registry", service_name, exc_info=True)
            return False, str(exc), service_name, "invoke_failed"

    ok, payload, code = await invoke_via_plugin_dotted_path(
        runtime, record, service_name, params
    )
    return (True, payload, service_name, None) if ok else (False, payload, service_name, code)
