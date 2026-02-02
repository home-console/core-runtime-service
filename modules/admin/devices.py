"""
Admin devices services (read-only).

Proxy to devices.* for list/get/list_external/list_mappings only.
Mutating operations (set_state, mappings) go through operations subsystem;
AdminModule does not contain plugin-specific or mutating device logic.
"""
from typing import Any, Optional


async def admin_devices_list(runtime: Any):
    return await runtime.service_registry.call("devices.list")


async def admin_devices_get(runtime: Any, id: Optional[str] = None, **kwargs):
    device_id = id or kwargs.get("device_id") or kwargs.get("deviceId")
    if not device_id:
        raise ValueError("device id is required")
    return await runtime.service_registry.call("devices.get", device_id)


async def admin_devices_list_external(runtime: Any, provider: Optional[str] = None, **kwargs):
    if provider is None:
        provider = kwargs.get("provider")
    return await runtime.service_registry.call("devices.list_external", provider)


async def admin_devices_list_mappings(runtime: Any) -> Any:
    try:
        return await runtime.service_registry.call("devices.list_mappings")
    except Exception as e:
        return {"ok": False, "error": str(e)}
