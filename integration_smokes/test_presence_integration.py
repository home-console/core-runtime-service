"""
Smoke-test для модуля presence (сервис и HTTP-контракты).
"""

from __future__ import annotations

import asyncio

import pytest

from app.bootstrap import APP_MODULES
from core.runtime.runtime import CoreRuntime
from plugins.test import AutomationStubPlugin, SystemLoggerPlugin


@pytest.mark.asyncio
async def test_presence(memory_adapter):
    runtime = CoreRuntime(memory_adapter)
    await runtime.module_manager.register_module_specs(runtime, APP_MODULES)

    logger = SystemLoggerPlugin(runtime)
    await runtime.plugin_manager.load_plugin(logger)

    automation = AutomationStubPlugin(runtime)
    await runtime.plugin_manager.load_plugin(automation)

    await runtime.start()
    await asyncio.sleep(0.1)

    services = await runtime.service_registry.list_services()
    assert "presence.set" in services

    endpoints = runtime.http.list()
    paths = [ep.path for ep in endpoints]
    assert "/api/v1/presence/enter" in paths
    assert "/api/v1/presence/leave" in paths

    cur = await runtime.storage.get("presence", "home")
    cur_val = cur.get("value") if isinstance(cur, dict) else cur
    assert cur_val is False

    await runtime.service_registry.call("presence.set", True)
    await asyncio.sleep(0.1)
    cur2 = await runtime.storage.get("presence", "home")
    cur2_val = cur2.get("value") if isinstance(cur2, dict) else cur2
    assert cur2_val is True

    await runtime.service_registry.call("presence.set", False)
    await asyncio.sleep(0.1)
    cur3 = await runtime.storage.get("presence", "home")
    cur3_val = cur3.get("value") if isinstance(cur3, dict) else cur3
    assert cur3_val is False

    await runtime.shutdown()
