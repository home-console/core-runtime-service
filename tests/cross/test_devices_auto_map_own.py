import pytest

from core.exceptions import ForbiddenError
from core.runtime.runtime import CoreRuntime
from modules.policy.engine import PolicyEngine as ModulePolicyEngine
from app.bootstrap import APP_MODULES


@pytest.mark.asyncio
async def test_auto_map_own_works_without_admin_context(memory_adapter):
    runtime = CoreRuntime(memory_adapter, policy_engine=ModulePolicyEngine())
    await runtime.module_manager.register_module_specs(runtime, APP_MODULES)
    await runtime.start()

    # No request/admin context set (ctx is None) — simulates a plugin-internal call.
    payload = {"external_id": "yandex_dev_1", "provider": "yandex", "name": "Yandex Lamp"}
    await runtime.event_bus.publish("external.device_discovered", payload)

    # devices.auto_map_own is not admin_only — must work without admin ctx.
    result = await runtime.service_registry.call("devices.auto_map_own", provider="yandex")
    assert result["ok"] is True
    assert result["created"] == 1

    mapping = await runtime.storage.get("devices_mappings", "yandex_dev_1")
    assert mapping is not None
    assert mapping["internal_id"] == "device-yandex_dev_1"

    device = await runtime.storage.get("devices", "device-yandex_dev_1")
    assert device is not None
    assert device["name"] == "Yandex Lamp"

    await runtime.shutdown()


@pytest.mark.asyncio
async def test_auto_map_own_requires_provider(memory_adapter):
    runtime = CoreRuntime(memory_adapter, policy_engine=ModulePolicyEngine())
    await runtime.module_manager.register_module_specs(runtime, APP_MODULES)
    await runtime.start()

    result = await runtime.service_registry.call("devices.auto_map_own", provider="")
    assert result["ok"] is False
    assert "provider" in result["error"]

    await runtime.shutdown()


@pytest.mark.asyncio
async def test_auto_map_external_still_requires_admin_context(memory_adapter):
    runtime = CoreRuntime(memory_adapter, policy_engine=ModulePolicyEngine())
    await runtime.module_manager.register_module_specs(runtime, APP_MODULES)
    await runtime.start()

    payload = {"external_id": "yandex_dev_2", "provider": "yandex", "name": "Yandex Socket"}
    await runtime.event_bus.publish("external.device_discovered", payload)

    # devices.auto_map_external remains admin_only — ctx=None must be rejected.
    with pytest.raises(ForbiddenError):
        await runtime.service_registry.call("devices.auto_map_external", provider="yandex")

    await runtime.shutdown()
