import pytest

from core.runtime.runtime import CoreRuntime
from core.errors import NotFoundError
from modules.api.auth.context import RequestContext
from modules.api.auth.contextvars import set_current_request_context
from modules.policy.engine import PolicyEngine as ModulePolicyEngine
from main import APP_MODULES


@pytest.mark.asyncio
async def test_devices_acl_enforced_on_services(memory_adapter):
    runtime = CoreRuntime(memory_adapter, policy_engine=ModulePolicyEngine())
    await runtime.module_manager.register_module_specs(runtime, APP_MODULES)
    await runtime.start()

    # Create device owned by user_a
    set_current_request_context(RequestContext(subject="user:user_a", user_id="user_a", scopes={"devices.*"}))
    await runtime.service_registry.call("devices.create", "dev1", name="Lamp", device_type="light")

    # Access as another user -> should look like not found (no disclosure)
    set_current_request_context(RequestContext(subject="user:user_b", user_id="user_b", scopes={"devices.*"}))
    with pytest.raises(NotFoundError):
        await runtime.service_registry.call("devices.get", "dev1")

    # Access as owner -> ok
    set_current_request_context(RequestContext(subject="user:user_a", user_id="user_a", scopes={"devices.*"}))
    dev = await runtime.service_registry.call("devices.get", "dev1")
    assert dev["id"] == "dev1"

    # list_devices returns only owned devices
    set_current_request_context(RequestContext(subject="user:user_b", user_id="user_b", scopes={"devices.*"}))
    lst = await runtime.service_registry.call("devices.list")
    assert all(d.get("owner_id") == "user_b" for d in lst)
    assert len(lst) == 0

    set_current_request_context(None)
    await runtime.stop()

