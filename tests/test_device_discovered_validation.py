import logging

import pytest

from core.runtime.runtime import CoreRuntime
from modules.devices.events import validate_device_discovered
from modules.events.registry import get_event_validator
from main import APP_MODULES


@pytest.mark.asyncio
async def test_validate_device_discovered_accepts_valid_payload(caplog):
    with caplog.at_level(logging.WARNING):
        await validate_device_discovered(
            {
                "external_id": "device-1",
                "provider": "yandex",
                "capabilities": {},
            }
        )

    assert not caplog.records


@pytest.mark.asyncio
async def test_validate_device_discovered_warns_for_missing_fields(caplog):
    with caplog.at_level(logging.WARNING):
        await validate_device_discovered({"provider": "yandex"})
        await validate_device_discovered({"external_id": "device-2"})

    messages = [record.message for record in caplog.records]

    assert any("Missing required field: external_id" in message for message in messages)
    assert any("Missing required field: provider" in message for message in messages)


@pytest.mark.asyncio
async def test_runtime_registers_device_discovered_validator(memory_adapter, monkeypatch):
    monkeypatch.setenv("TEST_MODE", "1")
    runtime = CoreRuntime(memory_adapter)

    await runtime.module_manager.register_module_specs(runtime, APP_MODULES)

    await runtime.start()

    validator = get_event_validator("external.device_discovered")
    assert validator is not None

    await runtime.stop()