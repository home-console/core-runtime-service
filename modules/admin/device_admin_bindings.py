from __future__ import annotations

import logging
from typing import Any

from core.http.models import EndpointAuthConfig, HttpEndpoint
from modules.api.schemas import (
    ApiResponse,
    DeviceDto,
    DeviceMappingDto,
    ExternalDeviceDto,
    OkErrorResponse,
    SetDeviceStateRequest,
)
from typing import List

logger = logging.getLogger(__name__)


async def register_device_admin_bindings(context: Any) -> list[str]:
    registered_services: list[str] = []
    services = context.services

    try:
        _admin_read = EndpointAuthConfig(required_scopes=["admin.read"])
        _admin_write = EndpointAuthConfig(required_scopes=["admin.write"])
        for endpoint in [
            HttpEndpoint(
                method="GET",
                path="/api/v1/admin/devices",
                service="admin.v1.devices.list",
                description="List internal devices",
                auth_config=_admin_read,
                tags=["Devices"],
                response_model=ApiResponse[List[DeviceDto]],
            ),
            HttpEndpoint(
                method="GET",
                path="/api/v1/admin/devices/{id}",
                service="admin.v1.devices.get",
                description="Get device by id",
                auth_config=_admin_read,
                tags=["Devices"],
                response_model=ApiResponse[DeviceDto],
            ),
            HttpEndpoint(
                method="GET",
                path="/api/v1/admin/devices/external/{provider}",
                service="admin.v1.devices.list_external",
                description="List external devices by provider",
                auth_config=_admin_read,
                tags=["Devices"],
                response_model=ApiResponse[List[ExternalDeviceDto]],
            ),
            HttpEndpoint(
                method="GET",
                path="/api/v1/admin/devices/external",
                service="admin.v1.devices.list_external",
                description="List all external devices (optional ?provider=<provider> to filter)",
                auth_config=_admin_read,
                tags=["Devices"],
                response_model=ApiResponse[List[ExternalDeviceDto]],
            ),
            HttpEndpoint(
                method="GET",
                path="/api/v1/admin/devices/mappings",
                service="admin.v1.devices.list_mappings",
                description="List device mappings",
                auth_config=_admin_read,
                tags=["Devices"],
                response_model=ApiResponse[List[DeviceMappingDto]],
            ),
            HttpEndpoint(
                method="GET",
                path="/api/v1/admin/devices/{id}/external",
                service="admin.v1.devices.get_external_for_device",
                description="Get external device payload for an internal device",
                auth_config=_admin_read,
                tags=["Devices"],
                response_model=ApiResponse[ExternalDeviceDto],
            ),
        ]:
            context.http.register(endpoint)

        async def _admin_set_state(device_id: str, body: dict = None, **kw):
            from core.runtime.auth_contextvars import (
                get_current_auth_context,
                set_current_auth_context,
            )
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

        context.http.register(
            HttpEndpoint(
                method="POST",
                path="/api/v1/admin/devices/{id}/state",
                service="admin.v1.devices.set_state",
                description="Set device desired state (proxy to devices.set_state)",
                auth_config=_admin_write,
                tags=["Devices"],
                response_model=OkErrorResponse,
                request_model=SetDeviceStateRequest,
            )
        )
    except Exception as e:
        logger.warning("Failed to register device admin bindings: %s", e, exc_info=True)

    return registered_services
