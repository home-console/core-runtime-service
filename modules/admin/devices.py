"""
Admin devices services (read-only).

Proxy to devices.* for list/get/list_external/list_mappings only.
Mutating operations (set_state, mappings) go through operations subsystem;
AdminModule does not contain plugin-specific or mutating device logic.
"""
from typing import Any, Optional
from core.system_context import create_system_context
from core.auth_contextvars import set_current_auth_context, get_current_auth_context


def _get_services(runtime: Any):
    # TODO: remove fallback after full KernelContext migration
    context = getattr(runtime, "context", None)
    if context is not None and hasattr(context, "get_service"):
        services = context.get_service("service_registry")
    else:
        services = getattr(runtime, "service_registry", None)
    return services


async def admin_devices_list(runtime: Any):
    ctx = create_system_context("admin", "devices.list")
    prev = get_current_auth_context()
    try:
        set_current_auth_context(ctx)
        services = _get_services(runtime)
        return await services.call("devices.list")
    finally:
        set_current_auth_context(prev)


async def admin_devices_get(runtime: Any, id: Optional[str] = None, **kwargs):
    device_id = id or kwargs.get("device_id") or kwargs.get("deviceId")
    if not device_id:
        raise ValueError("device id is required")
    ctx = create_system_context("admin", "devices.get")
    prev = get_current_auth_context()
    try:
        set_current_auth_context(ctx)
        services = _get_services(runtime)
        return await services.call("devices.get", device_id)
    finally:
        set_current_auth_context(prev)


async def admin_devices_list_external(runtime: Any, provider: Optional[str] = None, **kwargs):
    if provider is None:
        provider = kwargs.get("provider")
    ctx = create_system_context("admin", "devices.list_external")
    prev = get_current_auth_context()
    try:
        set_current_auth_context(ctx)
        services = _get_services(runtime)
        return await services.call("devices.list_external", provider)
    finally:
        set_current_auth_context(prev)


async def admin_devices_list_mappings(runtime: Any) -> Any:
    try:
        ctx = create_system_context("admin", "devices.list_mappings")
        prev = get_current_auth_context()
        try:
            set_current_auth_context(ctx)
            services = _get_services(runtime)
            return await services.call("devices.list_mappings")
        finally:
            set_current_auth_context(prev)
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def admin_devices_get_external_for_device(runtime: Any, id: Optional[str] = None, **kwargs: Any):
    """Вернуть внешний объект устройства (Яндекс и т.д.) по internal device id."""
    device_id = id or kwargs.get("device_id") or kwargs.get("deviceId")
    if not device_id:
        return None
    ctx = create_system_context("admin", "devices.get_external_for_device")
    prev = get_current_auth_context()
    try:
        set_current_auth_context(ctx)
        services = _get_services(runtime)
        return await services.call("devices.get_external_for_device", device_id)
    finally:
        set_current_auth_context(prev)
