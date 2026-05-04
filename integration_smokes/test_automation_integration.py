"""
Smoke-test цепочки: событие → automation_stub → logger.log.
"""

from __future__ import annotations

import asyncio

import pytest

from app.bootstrap import APP_MODULES
from core.runtime.runtime import CoreRuntime
from plugins.test import AutomationStubPlugin, SystemLoggerPlugin


@pytest.mark.asyncio
async def test_event_driven_automation(memory_adapter):
    runtime = CoreRuntime(memory_adapter)
    await runtime.module_manager.register_module_specs(runtime, APP_MODULES)

    logger = SystemLoggerPlugin(runtime)
    await runtime.plugin_manager.load_plugin(logger)

    automation = AutomationStubPlugin(runtime)
    await runtime.plugin_manager.load_plugin(automation)

    await runtime.start()

    plugins = await runtime.plugin_manager.list_plugins()
    assert "system_logger" in plugins
    assert "automation_stub" in plugins

    services = await runtime.service_registry.list_services()
    assert "logger.log" in services
    assert "devices.create" in services
    assert "devices.set_state" in services

    subscribers_count = await runtime.event_bus.get_subscribers_count(
        "internal.device_command_requested"
    )
    assert subscribers_count > 0

    await runtime.service_registry.call(
        "devices.create",
        device_id="test_light_1",
        name="Тестовая лампа",
        device_type="light",
    )

    await runtime.service_registry.call(
        "devices.set_state",
        "test_light_1",
        {"on": True},
    )
    await asyncio.sleep(0.2)

    await runtime.shutdown()
