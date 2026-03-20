import logging

import pytest

from core.runtime.runtime import CoreRuntime
from modules.events.validation import EventValidationMiddleware
from modules.events.registry import register_event_validator
from modules.devices.events import validate_external_device_state


@pytest.mark.asyncio
async def test_event_validation_middleware_warns_for_invalid_payload(caplog):
    # register validator for the test
    register_event_validator(
        "external.device_state_reported",
        validate_external_device_state,
    )

    middleware = EventValidationMiddleware()

    with caplog.at_level(logging.WARNING):
        await middleware.before_publish("external.device_state_reported", None)
        await middleware.before_publish(
            "external.device_state_reported",
            {"source": "bad-source"},
        )

    messages = [record.message for record in caplog.records]

    assert any("expected dict" in message for message in messages)
    assert any("Missing required field: external_id" in message for message in messages)
    assert any("Missing required field: state" in message for message in messages)
    assert any("Invalid value for 'source': bad-source" in message for message in messages)


@pytest.mark.asyncio
async def test_event_validation_middleware_accepts_optional_source(caplog):
    register_event_validator(
        "external.device_state_reported",
        validate_external_device_state,
    )

    middleware = EventValidationMiddleware()

    with caplog.at_level(logging.WARNING):
        await middleware.before_publish(
            "external.device_state_reported",
            {"external_id": "device-1", "state": {}},
        )
        await middleware.before_publish(
            "external.device_state_reported",
            {"external_id": "device-2", "state": {}, "source": "ws"},
        )

    assert not caplog.records


@pytest.mark.asyncio
async def test_runtime_registers_event_validation_middleware(
    memory_adapter, monkeypatch
):
    monkeypatch.setenv("TEST_MODE", "1")
    runtime = CoreRuntime(memory_adapter)

    await runtime.start()

    assert "EventValidationMiddleware" in await runtime.event_bus.list_middleware()

    await runtime.stop()
