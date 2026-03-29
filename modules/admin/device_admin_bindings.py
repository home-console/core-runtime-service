from __future__ import annotations

import logging
from typing import Any

from core.http.models import HttpEndpoint

logger = logging.getLogger(__name__)


async def register_device_admin_bindings(context: Any) -> list[str]:
    registered_services: list[str] = []
    runtime = context.runtime
    services = runtime.kernel_context.get_service("service_registry")

    try:
        for endpoint in [
            HttpEndpoint(method="GET", path="/admin/v1/devices", service="admin.v1.devices.list", description="List internal devices"),
            HttpEndpoint(method="GET", path="/admin/v1/devices/{id}", service="admin.v1.devices.get", description="Get device by id"),
            HttpEndpoint(method="GET", path="/admin/v1/devices/external/{provider}", service="admin.v1.devices.list_external", description="List external devices by provider"),
            HttpEndpoint(method="GET", path="/admin/v1/devices/external", service="admin.v1.devices.list_external", description="List all external devices (optional ?provider=yandex to filter)"),
            HttpEndpoint(method="GET", path="/admin/v1/devices/mappings", service="admin.v1.devices.list_mappings", description="List device mappings"),
            HttpEndpoint(method="GET", path="/admin/v1/devices/{id}/external", service="admin.v1.devices.get_external_for_device", description="Get external device payload (Yandex etc.) for an internal device"),
        ]:
            context.http.register(endpoint)

        async def _admin_set_state(device_id: str, body: dict = None, **kw):
            from core.runtime.auth_contextvars import get_current_auth_context, set_current_auth_context
            from core.runtime.system_context import create_system_context

            ctx = create_system_context("admin", "devices.set_state")
            prev = get_current_auth_context()
            try:
                payload = body
                if isinstance(body, dict) and "power" in body:
                    payload = {"state": {"on": body.get("power") == "on"}}
                set_current_auth_context(ctx)
                return await services.call("devices.set_state", device_id, payload)
            finally:
                set_current_auth_context(prev)

        # Admin auth is enforced at HTTP boundary; this handler sets a
        # trusted system context before delegating to devices.set_state.
        await services.register_with_acl(
            "admin.v1.devices.set_state",
            _admin_set_state,
            admin_only=False,
        )
        registered_services.append("admin.v1.devices.set_state")

        context.http.register(HttpEndpoint(
            method="POST",
            path="/admin/v1/devices/{id}/state",
            service="admin.v1.devices.set_state",
            description="Set device desired state (proxy to devices.set_state)",
        ))
    except Exception as e:
        logger.warning("Failed to register device admin bindings: %s", e, exc_info=True)

    return registered_services
