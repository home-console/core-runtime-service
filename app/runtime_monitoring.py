from __future__ import annotations

import time
from enum import Enum
from typing import Any, Dict

from core.kernel.plugin_registry import PluginState


class HealthStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


async def collect_runtime_health(runtime: Any) -> Dict[str, Any]:
    checks: Dict[str, str] = {}

    try:
        await runtime.storage.get("health_check", "test")
        checks["storage"] = HealthStatus.HEALTHY.value
    except Exception as exc:
        checks["storage"] = HealthStatus.UNHEALTHY.value
        checks["storage_error"] = str(exc)

    try:
        modules = runtime.module_manager.list_modules()
        required_modules = runtime.module_manager.get_required_modules()
        missing_required = [name for name in required_modules if name not in modules]
        if missing_required:
            checks["modules"] = HealthStatus.UNHEALTHY.value
            checks["modules_error"] = f"Missing required modules: {missing_required}"
        else:
            checks["modules"] = HealthStatus.HEALTHY.value
    except Exception as exc:
        checks["modules"] = HealthStatus.UNHEALTHY.value
        checks["modules_error"] = str(exc)

    load_errors: dict[str, str] = dict(getattr(runtime, "plugin_load_errors", {}) or {})

    try:
        plugins = await runtime.plugin_manager.list_plugins()
        error_plugins: list[str] = []
        for plugin_name in plugins:
            state = await runtime.plugin_manager.get_plugin_state(plugin_name)
            if state == PluginState.ERROR:
                error_plugins.append(plugin_name)
        if error_plugins:
            checks["plugins"] = HealthStatus.DEGRADED.value
            checks["plugins_error"] = f"Plugins in error state: {error_plugins}"
        elif load_errors:
            checks["plugins"] = HealthStatus.DEGRADED.value
            checks["plugins_error"] = "Plugin auto-load reported failures"
        else:
            checks["plugins"] = HealthStatus.HEALTHY.value
    except Exception as exc:
        checks["plugins"] = HealthStatus.UNHEALTHY.value
        checks["plugins_error"] = str(exc)

    if load_errors:
        checks["plugin_auto_load"] = HealthStatus.DEGRADED.value
        checks["plugin_load_errors"] = load_errors

    overall = HealthStatus.HEALTHY
    if any(value == HealthStatus.UNHEALTHY.value for value in checks.values()):
        overall = HealthStatus.UNHEALTHY
    elif any(value == HealthStatus.DEGRADED.value for value in checks.values()):
        overall = HealthStatus.DEGRADED

    return {
        "status": overall.value,
        "uptime": time.time() - runtime._start_time if runtime._start_time else 0,
        "checks": checks,
    }


async def collect_runtime_metrics(runtime: Any) -> Dict[str, Any]:
    metrics: Dict[str, Any] = {
        "uptime": time.time() - runtime._start_time if runtime._start_time else 0
    }

    try:
        plugins = await runtime.plugin_manager.list_plugins()
        plugin_states = {}
        for plugin_name in plugins:
            state = await runtime.plugin_manager.get_plugin_state(plugin_name)
            if state:
                plugin_states[plugin_name] = state.value
        started_count = sum(
            1 for state in plugin_states.values() if state == PluginState.STARTED.value
        )
        metrics["plugins"] = {
            "total": len(plugins),
            "started": started_count,
            "states": plugin_states,
        }
    except Exception:
        metrics["plugins"] = {"error": "failed to collect"}

    try:
        modules = runtime.module_manager.list_modules()
        metrics["modules"] = {"total": len(modules), "list": modules}
    except Exception:
        metrics["modules"] = {"error": "failed to collect"}

    try:
        services = await runtime.service_registry.list_services()
        metrics["services"] = {"total": len(services)}
    except Exception:
        metrics["services"] = {"error": "failed to collect"}

    try:
        await runtime.storage.get("metrics", "test")
        metrics["storage"] = {
            "available": True,
            "type": runtime.storage.get_backend_name(),
        }
    except Exception as exc:
        metrics["storage"] = {"available": False, "error": str(exc)}

    try:
        endpoints = runtime.http.list()
        metrics["http_endpoints"] = {"total": len(endpoints), "by_method": {}}
        for endpoint in endpoints:
            method = endpoint.method
            if method not in metrics["http_endpoints"]["by_method"]:
                metrics["http_endpoints"]["by_method"][method] = 0
            metrics["http_endpoints"]["by_method"][method] += 1
    except Exception:
        metrics["http_endpoints"] = {"error": "failed to collect"}

    return metrics
