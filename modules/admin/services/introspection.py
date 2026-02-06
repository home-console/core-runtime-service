"""
Inspector: read-only runtime snapshot (runtime mirror).

Читает ТОЛЬКО: plugin_manager, service_registry.list_services(), http.list(),
event_bus.list_subscriptions(), state, storage, operations.list_handler_types().
НЕ вызывает service_registry.call(). НЕ знает домены. НЕ агрегирует бизнес-модели.

Правило: если Inspector вызывает сервис — это баг.
Inspector = memory dump runtime, не API.
"""

from typing import Any, Dict, List
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
    Source: runtime.operations.list_handler_types() only. No service_registry.call, no domain logic.
    """
    ops = getattr(runtime, "operations", None)
    if not ops or not hasattr(ops, "list_handler_types"):
        return []
    types = ops.list_handler_types()
    return [{"type": t} for t in types]


# --- Execution observability (D3.3) ---

async def list_execution_traces(runtime: Any) -> List[Dict[str, Any]]:
    """
    Inspector view: список всех execution traces (read-only).

    Источник: runtime.storage, namespace \"execution\", ключи traces/{execution_id}.
    Никаких service_registry.call(), только прямое чтение storage.
    """
    try:
        keys = await runtime.storage.list_keys("execution")
    except Exception:
        return []

    result: List[Dict[str, Any]] = []
    for key in keys:
        if not key.startswith("traces/"):
            continue
        try:
            data = await runtime.storage.get("execution", key)
            if isinstance(data, dict):
                result.append(data)
        except Exception:
            continue
    return result


async def get_execution_trace(runtime: Any, execution_id: str) -> Dict[str, Any] | None:
    """
    Inspector view: получить одну трассу исполнения по execution_id.
    """
    if not execution_id:
        return None
    key = f"traces/{execution_id}"
    try:
        data = await runtime.storage.get("execution", key)
        if isinstance(data, dict):
            return data
    except Exception:
        return None
    return None


async def list_operation_executions(runtime: Any, operation_id: str) -> List[Dict[str, Any]]:
    """
    Inspector view: список execution'ов для конкретной операции.

    Источник: runtime.storage, namespace \"execution\", ключи by_operation/{operation_id}/{execution_id}.
    """
    if not operation_id:
        return []

    try:
        keys = await runtime.storage.list_keys("execution")
    except Exception:
        return []

    prefix = f"by_operation/{operation_id}/"
    result: List[Dict[str, Any]] = []
    for key in keys:
        if not key.startswith(prefix):
            continue
        try:
            data = await runtime.storage.get("execution", key)
            if isinstance(data, dict):
                result.append(data)
        except Exception:
            continue
    return result


# --- Execution schedules (D3.6) ---


async def list_schedules(runtime: Any) -> List[Dict[str, Any]]:
    """
    Inspector view: список всех расписаний execution.

    Источник: runtime.storage, namespace \"execution\", ключи schedules/{schedule_id}.
    """
    try:
        keys = await runtime.storage.list_keys("execution")
    except Exception:
        return []

    result: List[Dict[str, Any]] = []
    for key in keys:
        if not key.startswith("schedules/"):
            continue
        try:
            data = await runtime.storage.get("execution", key)
            if isinstance(data, dict):
                result.append(data)
        except Exception:
            continue
    return result


async def get_schedule(runtime: Any, schedule_id: str) -> Dict[str, Any] | None:
    """
    Inspector view: получить одно расписание по schedule_id.
    """
    if not schedule_id:
        return None
    key = f"schedules/{schedule_id}"
    try:
        data = await runtime.storage.get("execution", key)
        if isinstance(data, dict):
            return data
    except Exception:
        return None
    return None


async def list_operation_schedules(runtime: Any, operation_id: str) -> List[Dict[str, Any]]:
    """
    Inspector view: список расписаний для operation (operation_type).

    Источник: execution/schedules_by_operation/{operation_id}/{schedule_id}.
    """
    if not operation_id:
        return []

    try:
        keys = await runtime.storage.list_keys("execution")
    except Exception:
        return []

    prefix = f"schedules_by_operation/{operation_id}/"
    result: List[Dict[str, Any]] = []
    for key in keys:
        if not key.startswith(prefix):
            continue
        try:
            idx = await runtime.storage.get("execution", key)
            if not isinstance(idx, dict):
                continue
            sched_id = idx.get("schedule_id")
            if not sched_id:
                continue
            sched = await runtime.storage.get("execution", f"schedules/{sched_id}")
            if isinstance(sched, dict):
                result.append(sched)
        except Exception:
            continue
    return result


async def list_execution_retries(runtime: Any, execution_id: str) -> List[Dict[str, Any]]:
    """
    Inspector view: список retry-исполнений для заданного execution_id.

    Источник: namespace \"execution\", ключи by_parent/{execution_id}/{child_execution_id}.
    """
    if not execution_id:
        return []

    try:
        keys = await runtime.storage.list_keys("execution")
    except Exception:
        return []

    prefix = f"by_parent/{execution_id}/"
    result: List[Dict[str, Any]] = []
    for key in keys:
        if not key.startswith(prefix):
            continue
        try:
            idx = await runtime.storage.get("execution", key)
            if not isinstance(idx, dict):
                continue
            child_id = idx.get("execution_id")
            if not child_id:
                continue
            trace = await runtime.storage.get("execution", f"traces/{child_id}")
            if isinstance(trace, dict):
                result.append(trace)
        except Exception:
            continue

    # Сортируем по retry_index для предсказуемого порядка
    result.sort(key=lambda t: t.get("retry_index", 0))
    return result


async def get_execution_tree(runtime: Any, execution_id: str) -> Dict[str, Any] | None:
    """
    Inspector view: дерево retry для execution.

    Node:
      {
        execution_id,
        retry_index,
        status,
        backend,
        children: [...],
      }
    """
    if not execution_id:
        return None

    async def _build(node_id: str) -> Dict[str, Any] | None:
        tr = await runtime.storage.get("execution", f"traces/{node_id}")
        if not isinstance(tr, dict):
            return None
        children = await list_execution_retries(runtime, node_id)
        child_nodes: List[Dict[str, Any]] = []
        for ch in children:
            cid = ch.get("execution_id")
            if not cid:
                continue
            node = await _build(cid)
            if node:
                child_nodes.append(node)
        return {
            "execution_id": tr.get("execution_id"),
            "retry_index": tr.get("retry_index", 0),
            "status": tr.get("status"),
            "backend": tr.get("backend"),
            "children": child_nodes,
        }

    return await _build(execution_id)
