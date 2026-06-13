from __future__ import annotations

import logging
import asyncio
"""
Inspector: read-only runtime snapshot (runtime mirror).

Читает ТОЛЬКО: plugin_manager, service_registry.list_services(), http.list(),
event_bus.list_subscriptions(), state, storage, operations.list_handler_types().
НЕ вызывает service_registry.call(). НЕ знает домены. НЕ агрегирует бизнес-модели.

Правило: если Inspector вызывает сервис — это баг.
Inspector = memory dump runtime, не API.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
import time

from modules.plugins import PluginState
from core.adapters.storage_errors import STORAGE_BOUNDARY_ERRORS
from core.exceptions import NotFoundError
from core.observability.logger_helper import debug
from core.kernel.plugin_loader import PluginManifestLoader
from modules.api.route_binding import endpoint_mounted_path
logger = logging.getLogger(__name__)


async def _inspector_execution_list_keys(runtime: Any) -> List[str]:
    try:
        return await runtime.storage.list_keys("execution")
    except STORAGE_BOUNDARY_ERRORS:
        logger.debug("inspector: list_keys('execution') storage error", exc_info=True)
        return []
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("inspector: list_keys('execution') unexpected error", exc_info=True)
        return []


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
    except importlib.metadata.PackageNotFoundError:
        pass
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("Failed to read home-console package version", exc_info=True)
    
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
    for name in await pm.list_plugins():
        # Get plugin instance
        plugin = await pm.get_plugin(name)
        if not plugin:
            continue
        
        metadata = plugin.metadata
        
        services = []
        http_endpoints = []
        event_subscriptions = []
        
        try:
            all_services = await runtime.service_registry.list_services()
            services = [s for s in all_services if s.startswith(f"{name}.")]
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "list_plugins: service_registry.list_services failed for plugin %s",
                name,
                exc_info=True,
            )

        try:
            all_http = runtime.http.list()
            http_endpoints = [ep for ep in all_http if ep.service.startswith(f"{name}.")]
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "list_plugins: http.list failed for plugin %s",
                name,
                exc_info=True,
            )

        try:
            if hasattr(runtime, "event_bus") and runtime.event_bus:
                all_events = runtime.event_bus.list_subscriptions()
                for event_name, subs in all_events.items():
                    plugin_subs = [s for s in subs if s.get("plugin") == name]
                    if plugin_subs:
                        event_subscriptions.append(event_name)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "list_plugins: event_bus.list_subscriptions failed for plugin %s",
                name,
                exc_info=True,
            )
        
        # Get plugin state
        state = await pm.get_plugin_state(name)
        # Compare with PluginState enum value
        started = state == PluginState.STARTED
        
        # Get block reason if plugin is not started
        block_reason = await pm.get_plugin_block_reason(name)
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
            # Execution / isolation mode (for UI statistics)
            "execution_mode": getattr(metadata, "execution_mode", "in_process"),
        })

    return result


def _get_plugins_dir(runtime: Any) -> Optional[Path]:
    """Путь к каталогу плагинов из Config.plugins_dir. Возвращает None если не сконфигурировано."""
    config = getattr(runtime, "_config", None)
    plugins_dir_str = getattr(config, "plugins_dir", None) if config is not None else None
    if not plugins_dir_str:
        return None
    return Path(plugins_dir_str).expanduser()


async def discover_manifests_for_inspector(runtime: Any) -> Dict[str, Any]:
    """
    Inspector: список плагинов на диске (discovery из ядра).
    Источник: PluginManifestLoader.discover_manifests + topological_sort.
    Возвращает: manifests, load_order, plugins_dir, loaded (уже загруженные имена).
    """
    plugins_dir = _get_plugins_dir(runtime)
    loaded = list(await runtime.plugin_manager.list_plugins())
    if plugins_dir is None or not plugins_dir.exists() or not plugins_dir.is_dir():
        return {
            "plugins_dir": str(plugins_dir) if plugins_dir is not None else None,
            "manifests": {},
            "load_order": [],
            "loaded": loaded,
        }
    manifests = await PluginManifestLoader.discover_manifests(plugins_dir, runtime)  # type: ignore[arg-type]
    load_order = PluginManifestLoader.topological_sort(manifests, runtime)
    return {
        "plugins_dir": str(plugins_dir),
        "manifests": manifests,
        "load_order": load_order,
        "loaded": loaded,
    }


async def _load_plugin_manifest(runtime: Any, plugin_name: str) -> tuple[Optional[Dict[str, Any]], bool]:
    from core.kernel.plugin_loader import PluginManifestLoader

    name = str(plugin_name or "").strip()
    plugins_dir = _get_plugins_dir(runtime)
    if plugins_dir is None or not name:
        return None, False
    plugin_dir = PluginManifestLoader.find_plugin_directory(plugins_dir, name)
    if plugin_dir is None or not plugin_dir.exists():
        return None, False
    manifest = PluginManifestLoader.load_manifest(plugin_dir, strict=False)
    return manifest, manifest is not None


async def get_plugin_ui_config(runtime: Any, plugin_name: str) -> Optional[Dict[str, Any]]:
    """Inspector: read ``ui_config`` blob from plugin storage namespace."""
    from core.kernel.plugin_ui_config import PLUGIN_UI_CONFIG_KEY

    name = str(plugin_name or "").strip()
    if not name:
        return None
    manifest, on_disk = await _load_plugin_manifest(runtime, name)
    loaded = False
    if hasattr(runtime, "plugin_manager"):
        loaded = await runtime.plugin_manager.get_plugin(name) is not None
    if manifest is None and not loaded:
        return None

    config: Dict[str, Any] = {}
    if hasattr(runtime, "storage") and runtime.storage is not None:
        try:
            raw = await runtime.storage.get(name, PLUGIN_UI_CONFIG_KEY)
            if isinstance(raw, dict):
                config = raw
        except Exception:
            logger.debug("get_plugin_ui_config: storage read failed", exc_info=True)

    return {"plugin_name": name, "config": config}


async def set_plugin_ui_config(
    runtime: Any,
    plugin_name: str,
    config: Optional[Dict[str, Any]] = None,
    body: Any = None,
    **_: Any,
) -> Dict[str, Any]:
    """Inspector: write ``ui_config`` blob (admin)."""
    from core.kernel.plugin_ui_config import PLUGIN_UI_CONFIG_KEY

    name = str(plugin_name or "").strip()
    if not name:
        raise ValueError("plugin name required")

    payload: Dict[str, Any] = dict(config or {})
    if not payload and body is not None:
        if hasattr(body, "model_dump"):
            dumped = body.model_dump()
            if isinstance(dumped.get("config"), dict):
                payload = dict(dumped["config"])
        elif isinstance(body, dict):
            if isinstance(body.get("config"), dict):
                payload = dict(body["config"])
            else:
                payload = dict(body)

    if not hasattr(runtime, "storage") or runtime.storage is None:
        raise ValueError("storage not available")

    await runtime.storage.set(name, PLUGIN_UI_CONFIG_KEY, payload)
    return {"plugin_name": name, "config": payload}


async def invoke_plugin_service(
    runtime: Any,
    plugin_name: str,
    service: Optional[str] = None,
    kwargs: Optional[Dict[str, Any]] = None,
    body: Any = None,
    **__: Any,
) -> Dict[str, Any]:
    """Inspector: invoke allowlisted service for plugin UI (metric/table)."""
    from core.kernel.plugin_admin_invoke import service_allowed_for_plugin_invoke

    name = str(plugin_name or "").strip()
    svc = str(service or "").strip()
    call_kwargs: Dict[str, Any] = dict(kwargs or {})

    if not svc and body is not None:
        if hasattr(body, "model_dump"):
            dumped = body.model_dump()
            svc = str(dumped.get("service") or "").strip()
            if isinstance(dumped.get("kwargs"), dict):
                call_kwargs = dict(dumped["kwargs"])
        elif isinstance(body, dict):
            svc = str(body.get("service") or "").strip()
            if isinstance(body.get("kwargs"), dict):
                call_kwargs = dict(body["kwargs"])

    if not name or not svc:
        return {
            "ok": False,
            "plugin_name": name,
            "service": svc,
            "error": "plugin name and service required",
            "code": "invalid_request",
        }

    manifest, _ = await _load_plugin_manifest(runtime, name)
    if not service_allowed_for_plugin_invoke(name, svc, manifest):
        return {
            "ok": False,
            "plugin_name": name,
            "service": svc,
            "error": "service not allowed for plugin",
            "code": "forbidden_service",
        }

    registry = getattr(runtime, "service_registry", None)
    if registry is None:
        return {
            "ok": False,
            "plugin_name": name,
            "service": svc,
            "error": "service registry unavailable",
            "code": "invoke_not_configured",
        }

    has = await registry.has_service(svc)
    if not has:
        return {
            "ok": False,
            "plugin_name": name,
            "service": svc,
            "error": "service not registered",
            "code": "invoke_not_configured",
        }

    try:
        result = await registry.call(svc, **call_kwargs)
        return {
            "ok": True,
            "plugin_name": name,
            "service": svc,
            "result": result,
        }
    except Exception as exc:
        logger.warning("invoke_plugin_service failed %s.%s", name, svc, exc_info=True)
        return {
            "ok": False,
            "plugin_name": name,
            "service": svc,
            "error": str(exc),
            "code": "invoke_failed",
        }


async def list_dashboard_cards(runtime: Any) -> Dict[str, Any]:
    """
    Inspector: aggregate ``ui.dashboard_cards`` from all manifests on disk.

    Only server-driven cards (``type`` set, no legacy-only ``module``) are returned.
    """
    from core.kernel.plugin_loader import PluginManifestLoader
    from core.kernel.plugin_ui_contributions import _widget_dto

    plugins_dir = _get_plugins_dir(runtime)
    items: List[Dict[str, Any]] = []
    if plugins_dir is None:
        return {"items": items, "total": 0}

    manifests = await PluginManifestLoader.discover_manifests(plugins_dir, runtime)
    for plugin_name, manifest in manifests.items():
        if not isinstance(manifest, dict):
            continue
        ui = manifest.get("ui")
        if not isinstance(ui, dict):
            continue
        version = str(manifest.get("version") or "") or None
        for raw in ui.get("dashboard_cards") or []:
            if not isinstance(raw, dict):
                continue
            if raw.get("module") and not raw.get("type"):
                continue
            if not raw.get("type"):
                continue
            dto = _widget_dto(raw)
            dto["plugin_name"] = plugin_name
            dto["plugin_version"] = version
            items.append(dto)

    return {"items": items, "total": len(items)}


async def get_plugin_ui_contributions(runtime: Any, plugin_name: str) -> Optional[Dict[str, Any]]:
    """
    Inspector: server-driven UI declarations from plugin.json (§1.4 [1]).

    Includes legacy ``module`` entries for visibility; web must not dynamic-import them.
    """
    from core.kernel.plugin_ui_contributions import ui_contributions_from_manifest

    name = str(plugin_name or "").strip()
    if not name:
        return None

    manifest, on_disk = await _load_plugin_manifest(runtime, name)

    loaded = False
    if hasattr(runtime, "plugin_manager"):
        loaded = await runtime.plugin_manager.get_plugin(name) is not None

    if manifest is None and not loaded:
        return None

    return ui_contributions_from_manifest(
        name,
        manifest,
        loaded=loaded,
        on_disk=on_disk,
    )


async def get_plugin_details(runtime: Any, plugin_name: str) -> Optional[Dict[str, Any]]:
    """
    Inspector: детальная информация по одному плагину.
    Объединяет данные из реестра (если загружен) и манифеста на диске (если есть).
    """
    pm = runtime.plugin_manager
    plugins_dir = _get_plugins_dir(runtime)
    plugin_dir = plugins_dir / plugin_name if plugins_dir is not None else None
    manifest = PluginManifestLoader.load_manifest(plugin_dir) if plugin_dir is not None and plugin_dir.exists() else None

    # Если плагин загружен — полные данные как в list_plugins
    if await pm.get_plugin(plugin_name):
        plugins_list = await list_plugins(runtime)
        for p in plugins_list:
            if p.get("name") == plugin_name:
                out = dict(p)
                if manifest is not None:
                    out["manifest"] = manifest
                out["on_disk"] = manifest is not None
                return out

    # Плагин не загружен — только манифест с диска
    if manifest is not None:
        return {
            "name": plugin_name,
            "version": manifest.get("version", ""),
            "description": manifest.get("description", ""),
            "loaded": False,
            "started": False,
            "manifest": manifest,
            "on_disk": True,
            "dependencies": manifest.get("dependencies", []),
            "class_path": manifest.get("class_path"),
        }
    return None


async def list_services(runtime: Any) -> List[Dict[str, str]]:
    """List all registered services."""
    services = await runtime.service_registry.list_services()
    result = []
    for service in services:
        plugin_name = service.split(".")[0] if "." in service else "core"
        result.append({"service_name": service, "plugin_name": plugin_name})
    return result


async def list_http_endpoints(runtime: Any) -> List[Dict[str, Any]]:
    """List all HTTP endpoints (excluding WebSocket)."""
    endpoints = runtime.http.list()
    return [
        {
            "path": ep.path,
            "mounted_path": endpoint_mounted_path(runtime, ep),
            "method": ep.method,
            "websocket": ep.websocket,
            "service": ep.service,
            "description": ep.description,
            "tags": ep.tags or [],
        }
        for ep in endpoints
        if not ep.websocket
    ]


async def list_ws_endpoints(runtime: Any) -> List[Dict[str, Any]]:
    """List only WebSocket endpoints."""
    endpoints = runtime.http.list()
    return [
        {
            "path": ep.path,
            "mounted_path": endpoint_mounted_path(runtime, ep),
            "service": ep.service,
            "description": ep.description,
            "tags": ep.tags or [],
        }
        for ep in endpoints
        if ep.websocket
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


def _is_vault_namespace(ns: str) -> bool:
    """Проверка, что namespace относится к vault (секреты). В production не раскрываем содержимое."""
    vault_prefixes = ("secrets.store", "agent.private_keys", "agent.enrollment", "oauth.tokens", "ssh.credentials", "vault")
    return any(ns == p or ns.startswith(p + ".") for p in vault_prefixes)


def _is_debug() -> bool:
    """True если включён debug: DEBUG=1/true или DEBUG_MODE=1/true в .env."""
    import os
    v = (os.getenv("DEBUG") or os.getenv("DEBUG_MODE") or "false").lower().strip()
    return v in ("1", "true", "yes", "on")


async def list_storage_namespaces(runtime: Any) -> List[Dict[str, Any]]:
    """
    List all storage namespaces with key counts.
    В debug (DEBUG=1 или DEBUG_MODE=1): добавляет Security Store (secrets.store).
    В production: содержимое vault-namespace не раскрывается (ручка «закрыта»).
    """
    debug_mode = _is_debug()

    namespaces = await runtime.storage.list_namespaces()
    result = []
    for ns in namespaces:
        keys_count = None
        try:
            keys = await runtime.storage.list_keys(ns)
            keys_count = len(keys)
        except STORAGE_BOUNDARY_ERRORS:
            logger.debug(
                "list_storage_namespaces: list_keys failed for namespace %s",
                ns,
                exc_info=True,
            )
        except Exception:
            logger.warning(
                "list_storage_namespaces: unexpected error for namespace %s",
                ns,
                exc_info=True,
            )
        item = {"namespace": ns, "keys_count": keys_count}
        # В production не отдаём содержимое vault — только метаданные
        if not debug_mode and _is_vault_namespace(ns):
            item["restricted"] = True
        result.append(item)

    # В дебаге (DEBUG=1 или DEBUG_MODE=1): всегда показывать Security Store (secrets.store)
    has_secrets_item = any(item.get("namespace") == "secrets.store" for item in result)
    if debug_mode:
        store = getattr(runtime, "secret_store", None)
        if store is not None:
            try:
                if getattr(store, "_initialized", False):
                    keys_list = await store.list_secrets()
                    entries = {}
                    for key in keys_list:
                        try:
                            raw = await store.get(key)
                            if raw is None:
                                entries[key] = None
                            else:
                                try:
                                    entries[key] = raw.decode("utf-8", errors="replace")
                                except (TypeError, AttributeError, UnicodeDecodeError):
                                    entries[key] = (
                                        f"[binary, {len(raw) if raw is not None else 0} bytes]"
                                    )
                        except Exception as e:
                            logger.debug("introspection.list_storage_namespaces: error (using fallback value): %s", e)
                            entries[key] = {"error": str(e)}
                    if has_secrets_item:
                        for item in result:
                            if item.get("namespace") == "secrets.store":
                                item["debug_decrypted"] = True
                                item["entries"] = entries
                                item["keys_count"] = len(keys_list)
                                break
                    else:
                        result.append({
                            "namespace": "secrets.store",
                            "keys_count": len(keys_list),
                            "debug_decrypted": True,
                            "entries": entries,
                        })
                elif not has_secrets_item:
                    result.append({
                        "namespace": "secrets.store",
                        "keys_count": 0,
                        "debug_decrypted": False,
                        "_hint": "SecretStore not initialized; click to try loading",
                    })
            except Exception:
                logger.debug(
                    "list_storage_namespaces: secret_store debug branch failed",
                    exc_info=True,
                )
                if not has_secrets_item:
                    result.append({
                        "namespace": "secrets.store",
                        "keys_count": None,
                        "debug_decrypted": False,
                        "_hint": "Security Store (debug only)",
                    })
        elif not has_secrets_item:
            result.append({
                "namespace": "secrets.store",
                "keys_count": None,
                "debug_decrypted": False,
                "_hint": "Security Store (debug only); SecretStore not loaded",
            })

    return result


async def get_storage_namespace_contents(runtime: Any, namespace: str) -> Dict[str, Any]:
    """
    Получить все ключи и значения namespace (для inspector по клику на namespace).
    В production для vault-namespace возвращаем restricted.
    В debug (DEBUG=1 или DEBUG_MODE=1) для secrets.store используем SecretStore (расшифровка).
    """
    debug_mode = _is_debug()

    if not namespace or not isinstance(namespace, str):
        return {"namespace": namespace or "", "keys": [], "entries": {}, "error": "namespace required"}

    # Vault в production — не раскрываем содержимое
    if not debug_mode and _is_vault_namespace(namespace):
        return {
            "namespace": namespace,
            "keys": [],
            "entries": {},
            "restricted": True,
            "message": "Vault namespace content is not available in production.",
        }

    # secrets.store в debug — данные из SecretStore с расшифровкой
    if namespace == "secrets.store" and debug_mode and getattr(runtime, "secret_store", None):
        try:
            store = runtime.secret_store
            if getattr(store, "_initialized", False):
                keys_list = await store.list_secrets()
                entries = {}
                for key in keys_list:
                    try:
                        raw = await store.get(key)
                        if raw is None:
                            entries[key] = None
                        else:
                            try:
                                entries[key] = raw.decode("utf-8", errors="replace")
                            except (TypeError, AttributeError, UnicodeDecodeError):
                                entries[key] = (
                                    f"[binary, {len(raw) if raw is not None else 0} bytes]"
                                )
                    except Exception as e:
                        logger.debug("introspection.get_storage_namespace_contents: error (using fallback value): %s", e)
                        entries[key] = {"error": str(e)}
                return {
                    "namespace": namespace,
                    "keys": keys_list,
                    "entries": entries,
                    "debug_decrypted": True,
                }
        except Exception as e:
            logger.debug(
                "get_storage_namespace_contents: secrets.store debug branch failed",
                exc_info=True,
            )
            return {"namespace": namespace, "keys": [], "entries": {}, "error": str(e)}

    # Обычный storage: list_keys + get по каждому ключу
    try:
        keys = await runtime.storage.list_keys(namespace)
        entries = {}
        for key in keys:
            try:
                val = await runtime.storage.get(namespace, key)
                entries[key] = val
            except STORAGE_BOUNDARY_ERRORS as e:
                entries[key] = {"error": str(e)}
            except Exception as e:
                logger.debug(
                    "get_storage_namespace_contents: get failed for %s/%s",
                    namespace,
                    key,
                    exc_info=True,
                )
                entries[key] = {"error": str(e)}
        return {"namespace": namespace, "keys": keys, "entries": entries}
    except STORAGE_BOUNDARY_ERRORS as e:
        return {"namespace": namespace, "keys": [], "entries": {}, "error": str(e)}
    except Exception as e:
        logger.warning(
            "get_storage_namespace_contents: unexpected error for namespace %s",
            namespace,
            exc_info=True,
        )
        return {"namespace": namespace, "keys": [], "entries": {}, "error": str(e)}


async def get_state_snapshot(runtime: Any) -> Dict[str, Any]:
    """Inspector: полный снимок in-memory state (runtime.state.dump_snapshot())."""
    return await runtime.state.dump_snapshot()


async def get_state_keys(runtime: Any) -> List[str]:
    """Inspector: список ключей in-memory state."""
    return await runtime.state.keys()


async def get_state_value(runtime: Any, key: str) -> Any:
    """Inspector: значение по ключу in-memory state."""
    if not await runtime.state.exists(key):
        raise NotFoundError(f"state key not found: {key}")
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
    Source: storage only ("inspector"/"auth_flows").
    Plugins (OAuth, device auth, etc.) write flows; Inspector only reads.
    Если плагин выгружен или не запущен — state="unavailable", message="Временно недоступно".
    Returns list of { id, state, message?, actions: [{ type, label, params? }] }.
    """
    try:
        api = getattr(runtime, "api", None) or runtime
        storage_get = getattr(api, "storage_get", None)
        if not callable(storage_get):
            return []
        raw = await storage_get("inspector", "auth_flows")

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

        # Пометить привязки как «Временно недоступно», если нужные сервисы отсутствуют.
        # Это работает и для flow-объектов из storage (они не обязаны содержать plugin_name).
        flow_id_to_probe = _flow_id_to_probe_service_map()
        for flow in result:
            if not isinstance(flow, dict):
                continue
            fid = flow.get("id")
            if not isinstance(fid, str):
                continue
            probe_service = flow_id_to_probe.get(fid)
            if not probe_service:
                continue
            has = False
            try:
                has = await runtime.service_registry.has_service(probe_service)
            except Exception:
                logger.debug(
                    "list_auth_flows: has_service failed for %s",
                    probe_service,
                    exc_info=True,
                )
                has = False
            if not has:
                flow["state"] = "unavailable"
                flow["message"] = "Временно недоступно (сервис не зарегистрирован)"
                flow["_unavailable_reason"] = "service_unavailable"
        return result
    except Exception:
        logger.warning("list_auth_flows failed", exc_info=True)
        return []


def _flow_ids_set(flows: List[Dict[str, Any]]) -> set:
    """Собрать множество id из списка flow-объектов (id может быть str или None)."""
    out: set = set()
    for f in flows:
        if isinstance(f, dict) and f.get("id") is not None:
            out.add(f["id"])
    return out


# Auth flows, которые приходят из storage и не обязаны совпадать с каким-либо plugin-id.
# Для статуса "unavailable" используем probe через
# нейтральные сервисы, а не через имена плагинов.
_FLOW_ID_PROBE_SERVICES: Dict[str, str] = {}

# plugin_name -> flow id из state, которые считаются тем же плагином (дедуп в UI)
_PLUGIN_FLOW_ID_ALIASES: Dict[str, List[str]] = {}


def _flow_id_to_probe_service_map() -> Dict[str, str]:
    """Обратный маппинг: flow_id (id в UI) -> probe service."""
    return dict(_FLOW_ID_PROBE_SERVICES)


def _plugin_name_for_integration_item(item: Dict[str, Any]) -> Optional[str]:
    """Определить plugin_name для элемента списка интеграций (из state или реестра)."""
    pid = item.get("id")
    if isinstance(pid, str):
        return item.get("plugin_name") or pid
    return item.get("plugin_name")


async def list_integrations(runtime: Any) -> List[Dict[str, Any]]:
    """
    Inspector view: list integrations (read-only).
    Source: runtime.state["integration_inspector.integrations"] + auth_flows (storage).
    Fallback: runtime.integrations (IntegrationRegistry) — плагины с is_integration: true
    регистрируются при загрузке; если в state ничего не записали, показываем их как "available".
    Плагины могут писать в integration_inspector.integrations; auth-плагины для device-auth
    пишут auth flows в storage. Для единого списка в UI объединяем оба — тогда в «Интеграциях»
    видны и обычные интеграции, и привязки авторизаций (конкретные провайдеры и т.д.).
    Returns list of { id, state, message?, actions: [{ type, label, params? }] }.
    """
    result: List[Dict[str, Any]] = []
    state_count = 0
    registry_count = 0
    try:
        if hasattr(runtime, "state") and runtime.state is not None:
            data = await runtime.state.get("integration_inspector.integrations")
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        result.append(item)
            state_count = len(result)

        # Auth flows: storage (SDK-first).
        raw_flows = await list_auth_flows(runtime)
        for item in raw_flows:
            if not isinstance(item, dict):
                continue
            result.append(item)

        # Fallback: интеграции из реестра (плагины с is_integration в manifest),
        # чтобы список не был пустым, если плагины не пишут в state
        existing_ids = _flow_ids_set(result)
        if hasattr(runtime, "integrations") and runtime.integrations is not None:
            for info in runtime.integrations.list():
                if info.id in existing_ids:
                    continue
                # Не дублировать плагин, если у него уже есть flow из state (другой id)
                alias_ids = _PLUGIN_FLOW_ID_ALIASES.get(info.plugin_name, [])
                if any(aid in existing_ids for aid in alias_ids):
                    continue
                # Тип интеграции из реестра (oauth, capability_provider, integration) — для UI: разная кнопка для OAuth
                integration_type = getattr(info, "type", "integration") or "integration"
                is_oauth = (integration_type or "").lower() == "oauth"
                result.append({
                    "id": info.id,
                    "name": info.name,
                    "state": "available",
                    "message": info.description or None,
                    "integration_type": integration_type,
                    "actions": [
                        {
                            "type": "inspector.open_plugin",
                            "label": "Войти / Настроить OAuth" if is_oauth else "Настроить",
                            "params": {"plugin": info.plugin_name},
                        },
                    ],
                    "plugin_name": info.plugin_name,
                })
                registry_count += 1

        # Пометить привязки выгруженных/незапущенных плагинов как «Временно недоступно»
        pm = getattr(runtime, "plugin_manager", None)
        if pm is not None:
            for item in result:
                if not isinstance(item, dict):
                    continue
                plugin_name = _plugin_name_for_integration_item(item)
                if not plugin_name:
                    continue
                plugin = await pm.get_plugin(plugin_name)
                state = await pm.get_plugin_state(plugin_name)
                if plugin is None or state != PluginState.STARTED:
                    item["state"] = "unavailable"
                    item["message"] = "Временно недоступно (плагин выгружен или не запущен)"
                    item["_unavailable_reason"] = "plugin_unloaded" if plugin is None else "plugin_not_started"

        try:
            await debug(
                runtime,
                f"Inspector integrations: всего {len(result)} (из state: {state_count}, из реестра: {registry_count})",
                component="introspection",
            )
        except Exception:
            logger.warning("list_integrations: debug log failed", exc_info=True)
        return result
    except Exception:
        logger.warning("list_integrations failed", exc_info=True)
    return result



async def integrations_inspector_response(runtime: Any) -> list:
    """
    Ответ для GET /admin/v1/inspector/integrations: ApiResponse[List[IntegrationFlowDto]].
    """
    return await list_integrations(runtime)


async def auth_inspector_response(runtime: Any) -> list:
    """
    Ответ для GET /admin/v1/inspector/auth: ApiResponse[List[IntegrationFlowDto]].
    """
    return await list_auth_flows(runtime)


async def inventory_inspector_response(runtime: Any) -> Dict[str, Any]:
    """
    Ответ для GET /admin/v1/inspector/inventory.
    Пока возвращаем пустой список; при появлении источника инвентаря — заполнить.
    """
    return {"items": []}


async def inspector_auth_summary(runtime: Any) -> list:
    """
    Краткая сводка auth для Inspector (тот же формат, что auth_inspector_response).
    Регистрируется вторым handler'ом для admin.v1.inspector.auth — перезаписывает первый.
    """
    return await auth_inspector_response(runtime)


async def dashboard_inspector_response(runtime: Any) -> Dict[str, Any]:
    """
    Ответ для GET /admin/v1/inspector/dashboard: агрегат plugins, services, http_endpoints
    для главной страницы Admin UI (AdminDashboard).
    """
    try:
        plugins = await list_plugins(runtime)
        services = await list_services(runtime)
        http_endpoints = await list_http_endpoints(runtime)
    except Exception as e:
        logger.exception("dashboard_inspector_response failed")
        return {"ok": False, "error": str(e)}
    return {
        "plugins": len(plugins),
        "services": len(services),
        "http_endpoints": len(http_endpoints),
    }


# --- Execution observability ---

async def list_execution_traces(runtime: Any) -> List[Dict[str, Any]]:
    """
    Inspector view: список всех execution traces (read-only).

    Источник: runtime.storage, namespace \"execution\", ключи traces/{execution_id}.
    Никаких service_registry.call(), только прямое чтение storage.
    """
    keys = await _inspector_execution_list_keys(runtime)

    result: List[Dict[str, Any]] = []
    for key in keys:
        if not key.startswith("traces/"):
            continue
        try:
            data = await runtime.storage.get("execution", key)
            if isinstance(data, dict):
                result.append(data)
        except STORAGE_BOUNDARY_ERRORS:
            logger.debug("list_execution_traces: skip key %s (storage)", key, exc_info=True)
            continue
        except Exception:
            logger.debug("list_execution_traces: skip key %s (unexpected)", key, exc_info=True)
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
    except STORAGE_BOUNDARY_ERRORS:
        logger.debug(
            "get_execution_trace: storage error for %s",
            execution_id,
            exc_info=True,
        )
        return None
    except Exception:
        logger.warning(
            "get_execution_trace: unexpected error for %s",
            execution_id,
            exc_info=True,
        )
        return None
    return None


async def list_operation_executions(runtime: Any, operation_id: str) -> List[Dict[str, Any]]:
    """
    Inspector view: список execution'ов для конкретной операции.

    Источник: runtime.storage, namespace \"execution\", ключи by_operation/{operation_id}/{execution_id}.
    """
    if not operation_id:
        return []

    keys = await _inspector_execution_list_keys(runtime)

    prefix = f"by_operation/{operation_id}/"
    result: List[Dict[str, Any]] = []
    for key in keys:
        if not key.startswith(prefix):
            continue
        try:
            data = await runtime.storage.get("execution", key)
            if isinstance(data, dict):
                result.append(data)
        except STORAGE_BOUNDARY_ERRORS:
            logger.debug(
                "list_operation_executions: skip key %s (storage)",
                key,
                exc_info=True,
            )
            continue
        except Exception:
            logger.debug(
                "list_operation_executions: skip key %s (unexpected)",
                key,
                exc_info=True,
            )
            continue
    return result


# --- Execution schedules ---


async def list_schedules(runtime: Any) -> List[Dict[str, Any]]:
    """
    Inspector view: список всех расписаний execution.

    Источник: runtime.storage, namespace \"execution\", ключи schedules/{schedule_id}.
    """
    keys = await _inspector_execution_list_keys(runtime)

    result: List[Dict[str, Any]] = []
    for key in keys:
        if not key.startswith("schedules/"):
            continue
        try:
            data = await runtime.storage.get("execution", key)
            if isinstance(data, dict):
                result.append(data)
        except STORAGE_BOUNDARY_ERRORS:
            logger.debug("list_schedules: skip key %s (storage)", key, exc_info=True)
            continue
        except Exception:
            logger.debug("list_schedules: skip key %s (unexpected)", key, exc_info=True)
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
    except STORAGE_BOUNDARY_ERRORS:
        logger.debug("get_schedule: storage error for %s", schedule_id, exc_info=True)
        return None
    except Exception:
        logger.warning("get_schedule: unexpected error for %s", schedule_id, exc_info=True)
        return None
    return None


async def list_operation_schedules(runtime: Any, operation_id: str) -> List[Dict[str, Any]]:
    """
    Inspector view: список расписаний для operation (operation_type).

    Источник: execution/schedules_by_operation/{operation_id}/{schedule_id}.
    """
    if not operation_id:
        return []

    keys = await _inspector_execution_list_keys(runtime)

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
        except STORAGE_BOUNDARY_ERRORS:
            logger.debug(
                "list_operation_schedules: skip key %s (storage)",
                key,
                exc_info=True,
            )
            continue
        except Exception:
            logger.debug(
                "list_operation_schedules: skip key %s (unexpected)",
                key,
                exc_info=True,
            )
            continue
    return result


async def list_execution_retries(runtime: Any, execution_id: str) -> List[Dict[str, Any]]:
    """
    Inspector view: список retry-исполнений для заданного execution_id.

    Источник: namespace \"execution\", ключи by_parent/{execution_id}/{child_execution_id}.
    """
    if not execution_id:
        return []

    keys = await _inspector_execution_list_keys(runtime)

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
        except STORAGE_BOUNDARY_ERRORS:
            logger.debug(
                "list_execution_retries: skip key %s (storage)",
                key,
                exc_info=True,
            )
            continue
        except Exception:
            logger.debug(
                "list_execution_retries: skip key %s (unexpected)",
                key,
                exc_info=True,
            )
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
        logger.exception("list_capabilities failed")
    
    return result


async def get_system_health(runtime: Any) -> Dict[str, Any]:
    """
    Get system health snapshot including metrics and resource status.
    
    Observability endpoint for monitoring dashboard.
    """
    from core.observability.health_snapshot import HealthSnapshotCollector
    
    try:
        collector = HealthSnapshotCollector(runtime)
        snapshot = collector.collect()
        return {
            "status": "healthy" if snapshot.is_healthy() else "degraded",
            "details": snapshot.to_dict(),
        }
    except Exception as e:
        logger.warning("get_system_health: snapshot collection failed: %s", e, exc_info=True)
        return {
            "status": "unknown",
            "details": {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "error": str(e),
            },
        }
