"""
Inspector: read-only runtime snapshot.

Читает ТОЛЬКО: plugin_manager, service_registry.list_services(), http.list(),
event_bus.list_subscriptions(), state, storage, operations.list_handler_types().
Не вызывает service_registry.call(), не знает домены, не содержит if plugin_loaded.

Исключение: get_inventory собирает snapshot из read-only сервисов admin.v1.devices.*
(Control Plane Host собирает данные для UI; контракт для UI — ключи items, mappings, external).
"""

from typing import Any, Dict, List
import asyncio
import time


async def get_runtime_info(runtime: Any, admin_started_at: float | None) -> Dict[str, Any]:
    """Get runtime info: uptime, version, started_at."""
    uptime = None
    started_at = None
    if admin_started_at is not None:
        uptime = time.time() - admin_started_at
        started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(admin_started_at))
    
    version = "0.1.0"
    try:
        import importlib.metadata
        version = importlib.metadata.version("home-console")
    except Exception:
        pass
    
    return {
        "version": version,
        "started_at": started_at,
        "uptime": uptime,
    }


async def list_plugins(runtime: Any) -> List[Dict[str, Any]]:
    """List all loaded plugins with metadata."""
    plugins = runtime.plugins.list_plugins()
    result = []
    for p in plugins:
        services = []
        http_endpoints = []
        event_subscriptions = []
        
        try:
            all_services = await runtime.service_registry.list_services()
            services = [s for s in all_services if s.startswith(f"{p.name}.")]
        except Exception:
            pass
        
        try:
            all_http = runtime.http.list()
            http_endpoints = [ep for ep in all_http if ep.service.startswith(f"{p.name}.")]
        except Exception:
            pass
        
        try:
            if hasattr(runtime, "event_bus") and runtime.event_bus:
                all_events = runtime.event_bus.list_subscriptions()
                for event_name, subs in all_events.items():
                    plugin_subs = [s for s in subs if s.get("plugin") == p.name]
                    if plugin_subs:
                        event_subscriptions.append(event_name)
        except Exception:
            pass
        
        result.append({
            "name": p.name,
            "loaded": True,
            "started": p.started,
            "services_count": len(services),
            "http_count": len(http_endpoints),
            "event_subscriptions": event_subscriptions,
        })
    
    return result


async def list_services(runtime: Any) -> List[Dict[str, str]]:
    """List all registered services."""
    services = await runtime.service_registry.list_services()
    result = []
    for service in services:
        plugin_name = service.split(".")[0] if "." in service else "core"
        result.append({"service_name": service, "plugin_name": plugin_name})
    return result


async def list_http_endpoints(runtime: Any) -> List[Dict[str, Any]]:
    """List all HTTP endpoints."""
    endpoints = runtime.http.list()
    return [
        {
            "method": ep.method,
            "path": ep.path,
            "service": ep.service,
            "description": ep.description,
        }
        for ep in endpoints
    ]


async def list_events(runtime: Any) -> List[Dict[str, Any]]:
    """List event subscriptions."""
    if not hasattr(runtime, "event_bus") or runtime.event_bus is None:
        return []
    
    subscriptions = runtime.event_bus.list_subscriptions()
    result = []
    for event_name, subs in subscriptions.items():
        result.append({
            "event_name": event_name,
            "subscribers": [
                {"plugin": s.get("plugin", "unknown"), "handler": s.get("handler", "unknown")}
                for s in subs
            ],
        })
    return result


async def get_dashboard(runtime: Any, admin_started_at: float | None) -> Dict[str, Any]:
    """Aggregated endpoint for dashboard - returns all main data in one request."""
    try:
        # Parallel fetch of all data
        plugins_task = list_plugins(runtime)
        services_task = list_services(runtime)
        http_task = list_http_endpoints(runtime)
        state_keys_task = list_state_keys(runtime)
        runtime_info_task = get_runtime_info(runtime, admin_started_at)
        
        # Wait for all results
        plugins, services, http_endpoints, state_keys_data, runtime_info = await asyncio.gather(
            plugins_task,
            services_task,
            http_task,
            state_keys_task,
            runtime_info_task,
            return_exceptions=True
        )
        
        # Process possible errors
        result = {
            "ok": True,
            "summary": {
                "plugins": len(plugins) if not isinstance(plugins, Exception) else 0,
                "services": len(services) if not isinstance(services, Exception) else 0,
                "http_endpoints": len(http_endpoints) if not isinstance(http_endpoints, Exception) else 0,
                "state_keys": len(state_keys_data) if not isinstance(state_keys_data, Exception) else 0,
            },
            "runtime": runtime_info if not isinstance(runtime_info, Exception) else {"error": str(runtime_info)},
            "plugins": plugins if not isinstance(plugins, Exception) else [],
            "services": services if not isinstance(services, Exception) else [],
            "http_endpoints": http_endpoints if not isinstance(http_endpoints, Exception) else [],
            "state_keys": state_keys_data if not isinstance(state_keys_data, Exception) else [],
        }
        
        return result
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "summary": {
                "plugins": 0,
                "services": 0,
                "http_endpoints": 0,
                "state_keys": 0,
            }
        }


async def list_storage_namespaces(runtime: Any) -> List[Dict[str, Any]]:
    """List all storage namespaces with key counts."""
    namespaces = await runtime.storage.list_namespaces()
    result = []
    for ns in namespaces:
        keys_count = None
        try:
            keys = await runtime.storage.list_keys(ns)
            keys_count = len(keys)
        except Exception:
            pass
        result.append({"namespace": ns, "keys_count": keys_count})
    return result


async def get_state(runtime: Any) -> Dict[str, Any]:
    """Get all state keys and values."""
    if not hasattr(runtime, "state") or runtime.state is None:
        return {}
    
    keys = await runtime.state.list_keys()
    result = {}
    for key in keys:
        try:
            result[key] = await runtime.state.get(key)
        except Exception as e:
            result[key] = {"error": str(e)}
    return result


async def list_state_keys(runtime: Any) -> List[str]:
    """List all state keys."""
    if not hasattr(runtime, "state") or runtime.state is None:
        return []
    return await runtime.state.list_keys()


async def get_state_value(runtime: Any, key: str) -> Any:
    """Get state value by key."""
    if not hasattr(runtime, "state") or runtime.state is None:
        raise ValueError("State engine not available")
    return await runtime.state.get(key)


async def list_operations_available(runtime: Any) -> List[Dict[str, Any]]:
    """
    Inspector view: list available operation types (read-only).
    Source: runtime.operations.list_handler_types(). No service_registry.call, no domain logic.
    """
    ops = getattr(runtime, "operations", None)
    if not ops or not hasattr(ops, "list_handler_types"):
        return []
    types = ops.list_handler_types()
    return [{"type": t} for t in types]


async def get_inventory(runtime: Any) -> Dict[str, Any]:
    """
    Inspector view: read-only snapshot of inventory (items, mappings, external).
    Assembled by Control Plane from its own read-only services (admin.v1.devices.*).
    For UI only; keys are "items", "mappings", "external" (external is dict keyed by provider id).
    """
    result: Dict[str, Any] = {"items": [], "mappings": [], "external": {}}
    try:
        items = await runtime.service_registry.call("admin.v1.devices.list")
        if isinstance(items, list):
            result["items"] = items
    except Exception:
        pass
    try:
        mappings = await runtime.service_registry.call("admin.v1.devices.list_mappings")
        if isinstance(mappings, list):
            result["mappings"] = mappings
    except Exception:
        pass
    # External lists by provider; provider ids are opaque to UI (no domain names in UI)
    try:
        # Providers that expose list_external; backend knows ids, UI just iterates
        for provider_id in _inventory_external_providers():
            ext = await runtime.service_registry.call("admin.v1.devices.list_external", provider_id)
            if isinstance(ext, list):
                result["external"][provider_id] = ext
    except Exception:
        pass
    return result


def _inventory_external_providers() -> List[str]:
    """Provider ids that have list_external; used only for Inspector inventory assembly."""
    return ["yandex"]
