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

from core.plugin_manager import PluginState

from core.plugin_manager import PluginState


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
    """List all loaded plugins with metadata, including capabilities and block reasons."""
    result = []
    
    # Get all loaded plugins
    pm = runtime.plugin_manager
    for name in pm.list_plugins():
        # Get plugin instance
        plugin = pm.get_plugin(name)
        if not plugin:
            continue
        
        metadata = plugin.metadata
        
        services = []
        http_endpoints = []
        event_subscriptions = []
        
        try:
            all_services = await runtime.service_registry.list_services()
            services = [s for s in all_services if s.startswith(f"{name}.")]
        except Exception:
            pass

        try:
            all_http = runtime.http.list()
            http_endpoints = [ep for ep in all_http if ep.service.startswith(f"{name}.")]
        except Exception:
            pass

        try:
            if hasattr(runtime, "event_bus") and runtime.event_bus:
                all_events = runtime.event_bus.list_subscriptions()
                for event_name, subs in all_events.items():
                    plugin_subs = [s for s in subs if s.get("plugin") == name]
                    if plugin_subs:
                        event_subscriptions.append(event_name)
        except Exception:
            pass
        
        # Get plugin state
        state = pm.get_plugin_state(name)
        # Compare with PluginState enum value
        started = state == PluginState.STARTED
        
        # Get block reason if plugin is not started
        block_reason = pm.get_plugin_block_reason(name)
        error_msg = None
        unresolved_capabilities = []
        if block_reason:
            missing = block_reason.get("missing_capabilities", [])
            if missing:
                error_msg = f"Missing capabilities: {', '.join(missing)}"
                unresolved_capabilities = missing
        
        # Get capabilities from metadata
        capabilities_provided = metadata.capabilities_provided or []
        capabilities_required = metadata.capabilities_required or []
        
        # Calculate truly unresolved
        if capabilities_required and hasattr(runtime, "capability_registry"):
            cap_reg = runtime.capability_registry
            unresolved_capabilities = [
                cap for cap in capabilities_required
                if not cap_reg.get_providers(cap)
            ]

        result.append({
            "name": name,
            "version": metadata.version,
            "description": metadata.description,
            "loaded": True,
            "started": started,
            "error": error_msg,
            "services_count": len(services),
            "http_count": len(http_endpoints),
            "event_subscriptions": event_subscriptions,
            "capabilities_provided": capabilities_provided,
            "capabilities_required": capabilities_required,
            "unresolved_capabilities": unresolved_capabilities,
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
    """List all HTTP endpoints including WebSocket."""
    endpoints = runtime.http.list()
    return [
        {
            "path": ep.path,
            "method": ep.method,
            "websocket": ep.websocket,
            "service": ep.service,
            "description": ep.description,
            "tags": ep.tags or [],
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


async def list_auth_flows(runtime: Any) -> List[Dict[str, Any]]:
    """
    Inspector view: list auth flows (read-only).
    Source: runtime.state["auth_inspector.flows"] only. No service_registry.call.
    Plugins (OAuth, device auth, etc.) write to this state; Inspector only reads.
    Returns list of { id, state, message?, actions: [{ type, label, params? }] }.
    """
    try:
        if not hasattr(runtime, "state") or runtime.state is None:
            return []
        raw = await runtime.state.get("auth_inspector.flows")
        if not isinstance(raw, list):
            return []
        result = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            flow = {
                "id": item.get("id"),
                "state": item.get("state"),
                "actions": item.get("actions") if isinstance(item.get("actions"), list) else [],
            }
            if "message" in item and item["message"] is not None:
                flow["message"] = item["message"]
            if "qr_url" in item and item["qr_url"] is not None:
                flow["qr_url"] = item["qr_url"]
            if "qr_svg" in item and item["qr_svg"] is not None:
                flow["qr_svg"] = item["qr_svg"]
            result.append(flow)
        return result
    except Exception:
        return []


async def list_integrations(runtime: Any) -> List[Dict[str, Any]]:
    """
    Inspector view: list integrations (read-only).
    Source: runtime.state["integration_inspector.integrations"] + auth_inspector.flows.
    Плагины могут писать в integration_inspector.integrations; auth-плагины (yandex_device_auth)
    пишут в auth_inspector.flows. Для единого списка в UI объединяем оба — тогда в «Интеграциях»
    видны и обычные интеграции, и привязки авторизаций (Яндекс и т.д.).
    Returns list of { id, state, message?, actions: [{ type, label, params? }] }.
    """
    result: List[Dict[str, Any]] = []
    try:
        if not hasattr(runtime, "state") or runtime.state is None:
            return result
        data = await runtime.state.get("integration_inspector.integrations")
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    result.append(item)
        raw_flows = await runtime.state.get("auth_inspector.flows")
        if isinstance(raw_flows, list):
            for item in raw_flows:
                if not isinstance(item, dict):
                    continue
                flow = {
                    "id": item.get("id"),
                    "state": item.get("state"),
                    "actions": item.get("actions") if isinstance(item.get("actions"), list) else [],
                }
                if "message" in item and item["message"] is not None:
                    flow["message"] = item["message"]
                if "qr_url" in item and item["qr_url"] is not None:
                    flow["qr_url"] = item["qr_url"]
                if "qr_svg" in item and item["qr_svg"] is not None:
                    flow["qr_svg"] = item["qr_svg"]
                result.append(flow)
        return result
    except Exception:
        return result


async def integrations_inspector_response(runtime: Any) -> Dict[str, Any]:
    """
    Ответ для GET /admin/v1/inspector/integrations: { "integrations": [...] }.
    Клиент (Flutter) ожидает именно такой формат.
    """
    items = await list_integrations(runtime)
    return {"integrations": items}


async def auth_inspector_response(runtime: Any) -> Dict[str, Any]:
    """
    Ответ для GET /admin/v1/inspector/auth: { "auth_flows": [...] }.
    Клиент ожидает ключ auth_flows.
    """
    items = await list_auth_flows(runtime)
    return {"auth_flows": items}


async def inventory_inspector_response(runtime: Any) -> Dict[str, Any]:
    """
    Ответ для GET /admin/v1/inspector/inventory.
    Пока возвращаем пустой список; при появлении источника инвентаря — заполнить.
    """
    return {"items": []}


async def inspector_auth_summary(runtime: Any) -> Dict[str, Any]:
    """
    Краткая сводка auth для Inspector (тот же формат, что auth_inspector_response).
    Регистрируется вторым handler'ом для admin.v1.inspector.auth — перезаписывает первый.
    """
    return await auth_inspector_response(runtime)


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

async def list_capabilities(runtime: Any) -> List[Dict[str, Any]]:
    """
    List all registered capabilities and their providers.
    
    Returns list of capabilities with their providers, types, and remote config.
    """
    result = []
    
    if not hasattr(runtime, 'capability_registry') or not runtime.capability_registry:
        return result
    
    cap_reg = runtime.capability_registry
    
    # Get all capabilities with full provider info
    try:
        capabilities = {}
        for capability_id, providers in cap_reg._providers.items():
            # Build provider list with full info
            provider_list = []
            for provider_info in providers:
                provider_dict = {
                    "name": provider_info.get("name"),
                    "type": provider_info.get("type", "local"),
                }
                # Include remote_config only for remote providers
                if provider_info.get("type") == "remote" and provider_info.get("remote_config"):
                    provider_dict["base_url"] = provider_info["remote_config"].get("base_url")
                    provider_dict["timeout"] = provider_info["remote_config"].get("timeout", 10)
                
                provider_list.append(provider_dict)
            
            # Determine primary provider (first one, prefer local)
            local_providers = [p for p in provider_list if p["type"] == "local"]
            remote_providers = [p for p in provider_list if p["type"] == "remote"]
            primary = local_providers[0] if local_providers else (remote_providers[0] if remote_providers else None)
            
            capabilities[capability_id] = {
                "id": capability_id,
                "providers": provider_list,
                "primary_provider": primary,
                "provider_count": len(provider_list),
                "local_provider_count": len(local_providers),
                "remote_provider_count": len(remote_providers),
            }
        
        # Sort by id for stable output
        for cap_id in sorted(capabilities.keys()):
            result.append(capabilities[cap_id])
    except Exception:
        pass
    
    return result