from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any, Optional

from app.orchestration import OrchestrationService
from core.http.models import EndpointAuthConfig, HttpEndpoint
from modules.api.schemas import (
    AutoLoadRequest,
    EnsureContainerRequest,
    LoadPluginRequest,
    OkErrorResponse,
)

logger = logging.getLogger(__name__)


async def register_plugin_control_bindings(
    runtime: Any,
    context: Any,
    orchestration_service: Optional[OrchestrationService],
) -> list[str]:
    registered_services: list[str] = []

    async def _admin_unload_plugin(name: str = None, **kw):
        plugin_name = name or kw.get("name")
        if not plugin_name:
            return {"ok": False, "error": "Имя плагина не указано"}
        try:
            await runtime.plugin_manager.unload_plugin(plugin_name)
            return {"ok": True}
        except Exception as e:
            logger.warning(
                "plugin_control_bindings._admin_unload_plugin: failed: %s",
                e,
                exc_info=True,
            )
            return {"ok": False, "error": str(e)}

    async def _admin_reload_plugin(name: str = None, **kw):
        plugin_name = name or kw.get("name")
        if not plugin_name:
            return {"ok": False, "error": "Имя плагина не указано"}
        try:
            await runtime.plugin_manager.reload_plugin(plugin_name)
            return {"ok": True}
        except Exception as e:
            logger.warning(
                "plugin_control_bindings._admin_reload_plugin: failed: %s",
                e,
                exc_info=True,
            )
            return {"ok": False, "error": str(e)}

    async def _admin_restart_plugin_container(name: str = None, body: Any = None, **kw):
        plugin_name = name or kw.get("name")
        if not plugin_name:
            return {"ok": False, "error": "Имя плагина не указано"}
        if orchestration_service is None:
            return {"ok": False, "error": "OrchestrationService недоступен"}

        plugin = await runtime.plugin_manager.get_plugin(plugin_name)
        if not plugin:
            return {"ok": False, "error": f"Плагин '{plugin_name}' не найден"}

        metadata = plugin.metadata
        if metadata.execution_mode != "container":
            return {
                "ok": False,
                "error": (
                    f"Плагин '{plugin_name}' не является container плагином "
                    f"(execution_mode: {metadata.execution_mode}). Используйте reload для перезапуска."
                ),
            }
        if not metadata.container_config:
            return {
                "ok": False,
                "error": f"У плагина '{plugin_name}' не указан container_config в metadata",
            }

        container_name = None
        if isinstance(body, dict):
            container_name = body.get("container_name")
        if not container_name:
            container_name = metadata.container_config.get("name")
        if not container_name:
            container_name = f"plugin-{plugin_name}"

        if not shutil.which("docker"):
            return {"ok": False, "error": "Docker не найден в системе"}

        container_exists = await orchestration_service.container_exists(container_name)
        if not container_exists:
            logger.info(
                "Container %s not found, attempting to ensure it exists", container_name
            )
            ensure_result = await orchestration_service.ensure_container(
                container_name,
                metadata.container_config,
            )
            if not ensure_result["ok"]:
                return ensure_result

        logger.info(
            "Restarting container %s for plugin %s", container_name, plugin_name
        )
        restart_result = await orchestration_service.restart_container(
            container_name, timeout=30.0
        )
        if restart_result["ok"]:
            logger.info("Container %s restarted successfully", container_name)
            return restart_result

        error_msg = restart_result.get("error", "Неизвестная ошибка")
        logger.warning("Failed to restart container %s: %s", container_name, error_msg)
        if "network" in error_msg.lower() and "not found" in error_msg.lower():
            logger.info(
                "Network error detected, recreating container %s", container_name
            )
            remove_result = await orchestration_service.remove_container(
                container_name, force=True
            )
            if not remove_result["ok"]:
                return {
                    "ok": False,
                    "error": (
                        f"Не удалось перезапустить контейнер '{container_name}': {error_msg}. "
                        "Также не удалось удалить контейнер для пересоздания: "
                        f"{remove_result.get('error', 'неизвестная ошибка')}"
                    ),
                }
            ensure_result = await orchestration_service.ensure_container(
                container_name,
                metadata.container_config,
            )
            if ensure_result["ok"]:
                return {
                    "ok": True,
                    "message": f"Контейнер '{container_name}' пересоздан и запущен (была проблема с сетью)",
                }
            return ensure_result

        return restart_result

    async def _admin_ensure_plugin_container(name: str = None, body: Any = None, **kw):
        plugin_name = name or kw.get("name")
        if not plugin_name:
            return {"ok": False, "error": "Имя плагина не указано"}
        if orchestration_service is None:
            return {"ok": False, "error": "OrchestrationService недоступен"}

        plugin = await runtime.plugin_manager.get_plugin(plugin_name)
        if not plugin:
            return {"ok": False, "error": f"Плагин '{plugin_name}' не найден"}

        metadata = plugin.metadata
        if metadata.execution_mode != "container":
            return {
                "ok": False,
                "error": (
                    f"Плагин '{plugin_name}' не является container плагином "
                    f"(execution_mode: {metadata.execution_mode}). Используйте reload для перезапуска."
                ),
            }
        if not metadata.container_config:
            return {
                "ok": False,
                "error": f"У плагина '{plugin_name}' не указан container_config в metadata",
            }

        container_name = None
        if isinstance(body, dict):
            container_name = body.get("container_name")
        if not container_name:
            container_name = metadata.container_config.get("name")
        if not container_name:
            container_name = f"plugin-{plugin_name}"

        return await orchestration_service.ensure_container(
            container_name, metadata.container_config
        )

    async def _admin_start_plugin(name: str = None, **kw):
        plugin_name = name or kw.get("name")
        if not plugin_name:
            return {"ok": False, "error": "Имя плагина не указано"}
        try:
            await runtime.plugin_manager.start_plugin(plugin_name)
            return {"ok": True}
        except Exception as e:
            logger.warning(
                "plugin_control_bindings._admin_start_plugin: failed: %s",
                e,
                exc_info=True,
            )
            return {"ok": False, "error": str(e)}

    async def _admin_stop_plugin(name: str = None, **kw):
        plugin_name = name or kw.get("name")
        if not plugin_name:
            return {"ok": False, "error": "Имя плагина не указано"}
        try:
            await runtime.plugin_manager.stop_plugin(plugin_name)
            return {"ok": True}
        except Exception as e:
            logger.warning(
                "plugin_control_bindings._admin_stop_plugin: failed: %s",
                e,
                exc_info=True,
            )
            return {"ok": False, "error": str(e)}

    async def _admin_load_plugin_by_name(name: str = None, body: Any = None, **kw):
        plugin_name = (
            name or (isinstance(body, dict) and body.get("name")) or kw.get("name")
        )
        if not plugin_name:
            return {"ok": False, "error": "Имя плагина не указано"}
        try:
            plugins_dir = None
            if isinstance(body, dict) and body.get("plugins_dir"):
                plugins_dir = Path(body["plugins_dir"])
            ok = await runtime.plugin_manager.load_plugin_by_name(
                plugin_name, plugins_dir=plugins_dir
            )
            if ok:
                return {"ok": True}
            return {
                "ok": False,
                "error": f"Не удалось загрузить плагин '{plugin_name}' (нет манифеста или зависимости)",
            }
        except Exception as e:
            logger.warning(
                "plugin_control_bindings._admin_load_plugin_by_name: failed: %s",
                e,
                exc_info=True,
            )
            return {"ok": False, "error": str(e)}

    async def _admin_auto_load_plugins(body: Any = None, **kw):
        plugins_dir = None
        if isinstance(body, dict) and body.get("plugins_dir"):
            plugins_dir = Path(body["plugins_dir"])
        try:
            await runtime.plugin_manager.auto_load_plugins(plugins_dir=plugins_dir)
            return {"ok": True, "loaded": await runtime.plugin_manager.list_plugins()}
        except Exception as e:
            logger.warning(
                "plugin_control_bindings._admin_auto_load_plugins: failed: %s",
                e,
                exc_info=True,
            )
            return {"ok": False, "error": str(e)}

    handlers = [
        ("admin.v1.plugins.unload", _admin_unload_plugin),
        ("admin.v1.plugins.reload", _admin_reload_plugin),
        ("admin.v1.plugins.restart_container", _admin_restart_plugin_container),
        ("admin.v1.plugins.ensure_container", _admin_ensure_plugin_container),
        ("admin.v1.plugins.start", _admin_start_plugin),
        ("admin.v1.plugins.stop", _admin_stop_plugin),
        ("admin.v1.plugins.load_by_name", _admin_load_plugin_by_name),
        ("admin.v1.plugins.auto_load", _admin_auto_load_plugins),
    ]
    try:
        services = context.services
        for name, handler in handlers:
            await services.register_with_acl(name, handler, admin_only=True)
            registered_services.append(name)
    except Exception as e:
        logger.warning(
            "Failed to register plugin control services: %s", e, exc_info=True
        )

    try:
        _admin_write = EndpointAuthConfig(required_scopes=["admin.write"])
        for endpoint in [
            HttpEndpoint(
                method="POST",
                path="/api/v1/admin/plugins/{name}/unload",
                service="admin.v1.plugins.unload",
                description="Unload plugin by name (admin only)",
                auth_config=_admin_write,
                tags=["Plugins"],
                response_model=OkErrorResponse,
            ),
            HttpEndpoint(
                method="POST",
                path="/api/v1/admin/plugins/{name}/reload",
                service="admin.v1.plugins.reload",
                description="Reload plugin by name (admin only)",
                auth_config=_admin_write,
                tags=["Plugins"],
                response_model=OkErrorResponse,
            ),
            HttpEndpoint(
                method="POST",
                path="/api/v1/admin/plugins/{name}/restart-container",
                service="admin.v1.plugins.restart_container",
                description="Restart plugin container by name (admin only)",
                auth_config=_admin_write,
                tags=["Plugins"],
                response_model=OkErrorResponse,
                request_model=EnsureContainerRequest,
            ),
            HttpEndpoint(
                method="POST",
                path="/api/v1/admin/plugins/{name}/ensure-container",
                service="admin.v1.plugins.ensure_container",
                description="Ensure plugin container exists (build and create if needed, admin only)",
                auth_config=_admin_write,
                tags=["Plugins"],
                response_model=OkErrorResponse,
                request_model=EnsureContainerRequest,
            ),
            HttpEndpoint(
                method="POST",
                path="/api/v1/admin/plugins/{name}/start",
                service="admin.v1.plugins.start",
                description="Start plugin by name (kernel: plugin_manager.start_plugin)",
                auth_config=_admin_write,
                tags=["Plugins"],
                response_model=OkErrorResponse,
            ),
            HttpEndpoint(
                method="POST",
                path="/api/v1/admin/plugins/{name}/stop",
                service="admin.v1.plugins.stop",
                description="Stop plugin by name (kernel: plugin_manager.stop_plugin)",
                auth_config=_admin_write,
                tags=["Plugins"],
                response_model=OkErrorResponse,
            ),
            HttpEndpoint(
                method="POST",
                path="/api/v1/admin/plugins/load",
                service="admin.v1.plugins.load_by_name",
                description="Load one plugin by name from plugins dir (kernel: load_plugin_by_name)",
                auth_config=_admin_write,
                tags=["Plugins"],
                response_model=OkErrorResponse,
                request_model=LoadPluginRequest,
            ),
            HttpEndpoint(
                method="POST",
                path="/api/v1/admin/plugins/{name}/load",
                service="admin.v1.plugins.load_by_name",
                description="Load one plugin by name from path (kernel: load_plugin_by_name)",
                auth_config=_admin_write,
                tags=["Plugins"],
                response_model=OkErrorResponse,
                request_model=LoadPluginRequest,
            ),
            HttpEndpoint(
                method="POST",
                path="/api/v1/admin/plugins/auto-load",
                service="admin.v1.plugins.auto_load",
                description="Rescan plugins dir and load from manifests (kernel: auto_load_plugins)",
                auth_config=_admin_write,
                tags=["Plugins"],
                response_model=OkErrorResponse,
                request_model=AutoLoadRequest,
            ),
        ]:
            context.http.register(endpoint)
    except Exception as e:
        logger.warning(
            "Failed to register plugin control HTTP endpoints: %s", e, exc_info=True
        )

    return registered_services
