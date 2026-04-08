import pytest

from core.kernel.plugin_api import PluginAPI
from sdk.operations_events import OPERATION_READY_EVENT_TYPE


@pytest.mark.asyncio
async def test_plugin_api_publish_operation_ready_delegates_to_bus():
    calls: list[tuple[str, dict]] = []

    class Bus:
        async def publish(self, event_type: str, payload: dict) -> None:
            calls.append((event_type, dict(payload)))

    api = PluginAPI(
        service_registry=None,
        event_bus=Bus(),
        storage=None,
        operations=None,
        http=None,
    )
    await api.publish_operation_ready("op-xyz", foo=1)

    assert len(calls) == 1
    et, payload = calls[0]
    assert et == OPERATION_READY_EVENT_TYPE
    assert payload["operation_id"] == "op-xyz"
    assert payload["type"] == OPERATION_READY_EVENT_TYPE
    assert payload["foo"] == 1
