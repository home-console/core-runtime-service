import asyncio
import pytest

from core.runtime import CoreRuntime
from plugins.system_logger_plugin import SystemLoggerPlugin
from plugins.admin_plugin import AdminPlugin


async def _call_http(runtime: CoreRuntime, method: str, path: str, body=None):
    """Simple http simulator: finds matching HttpEndpoint and calls service.

    Matching supports templates like /admin/v1/devices/{id}/state
    Returns the service call result.
    """
    method = method.upper()
    endpoints = runtime.http.list()

    for ep in endpoints:
        if ep.method != method:
            continue
        tmpl_parts = ep.path.strip("/").split("/") if ep.path != "/" else [""]
        path_parts = path.strip("/").split("/") if path != "/" else [""]
        if len(tmpl_parts) != len(path_parts):
            continue
        params = []
        matched = True
        for tpart, ppart in zip(tmpl_parts, path_parts):
            if tpart.startswith("{") and tpart.endswith("}"):
                params.append(ppart)
            elif tpart == ppart:
                continue
            else:
                matched = False
                break
        if not matched:
            continue

        # Prepare args: positional params from path, then body for POST if present
        call_args = list(params)
        if method == "POST" and body is not None:
            call_args.append(body)

        # Call service via service_registry
        return await runtime.service_registry.call(ep.service, *call_args)

    raise AssertionError(f"No matching endpoint for {method} {path}")


@pytest.mark.asyncio
async def test_admin_devices_end_to_end(memory_adapter):
    runtime = CoreRuntime(memory_adapter)

    # Load necessary plugins
    logger = SystemLoggerPlugin(runtime)
    admin = AdminPlugin(runtime)

    await runtime.plugin_manager.load_plugin(logger)
    await runtime.plugin_manager.load_plugin(admin)

    # Start runtime (invokes on_start of plugins)
    await runtime.start()

    # 1. GET /admin/v1/devices -> initially empty list
    res = await _call_http(runtime, "GET", "/admin/v1/devices")
    assert isinstance(res, list)

    # 2. Publish external device discovered (provider: yandex)
    payload = {"external_id": "yandex_1", "provider": "yandex", "name": "Yandex Lamp"}
    await runtime.event_bus.publish("external.device_discovered", payload)

    # 3. GET external devices for provider yandex
    ext = await _call_http(runtime, "GET", "/admin/v1/devices/external/yandex")
    assert isinstance(ext, list)
    assert any(e.get("external_id") == "yandex_1" for e in ext)

    # 4. Create internal device and change state via admin HTTP POST
    await runtime.service_registry.call("devices.create", "dev_integ_1", name="Integration Lamp", device_type="light")

    # Ensure current state is off
    d = await _call_http(runtime, "GET", "/admin/v1/devices/dev_integ_1")
    assert d["id"] == "dev_integ_1"
    # New state model: {desired, reported, pending}
    assert d["state"]["desired"]["on"] is False
    assert d["state"]["reported"]["on"] is False

    # POST to set state -> turn on
    await _call_http(runtime, "POST", "/admin/v1/devices/dev_integ_1/state", {"power": "on"})

    # Verify state changed
    d2 = await runtime.service_registry.call("devices.get", "dev_integ_1")
    # Check that desired state was updated and pending is set
    assert d2["state"]["desired"]["on"] is True
    assert d2["state"]["pending"] is True

    # Shutdown
    await runtime.shutdown()
