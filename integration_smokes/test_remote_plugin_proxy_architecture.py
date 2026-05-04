"""
Smoke-test для архитектуры remote plugins.

Проверяет RemotePluginProxy при живом Core Runtime (in-memory storage).
"""

from __future__ import annotations

import pytest

from app.bootstrap import APP_MODULES
from core.runtime.runtime import CoreRuntime
from plugins.remote_plugin_proxy import RemotePluginProxy
from plugins.test import SystemLoggerPlugin


@pytest.mark.asyncio
async def test_remote_plugin_proxy_architecture(memory_adapter):
    runtime = CoreRuntime(memory_adapter)
    await runtime.module_manager.register_module_specs(runtime, APP_MODULES)

    logger = SystemLoggerPlugin(runtime)
    await runtime.plugin_manager.load_plugin(logger)

    await runtime.start()

    remote_proxy = RemotePluginProxy(runtime, "http://127.0.0.1:8001")

    async def mock_http_call(endpoint, method="GET", json_data=None):
        if endpoint == "/plugin/metadata":
            return {
                "name": "remote_logger",
                "version": "0.1.0",
                "type": "system",
                "mode": "remote",
                "description": "Логирование как удалённый сервис",
            }
        if endpoint == "/plugin/load":
            return {"status": "ok", "message": "plugin loaded"}
        if endpoint == "/plugin/start":
            return {"status": "ok", "message": "plugin started"}
        if endpoint == "/plugin/stop":
            return {"status": "ok", "message": "plugin stopped"}
        if endpoint == "/plugin/unload":
            return {"status": "ok", "message": "plugin unloaded"}
        raise ValueError(f"Unknown endpoint: {endpoint}")

    remote_proxy._http_call = mock_http_call

    await runtime.plugin_manager.load_plugin(remote_proxy)

    plugins = await runtime.plugin_manager.list_plugins()
    assert "system_logger" in plugins

    devices_list = await runtime.service_registry.call("devices.list")
    assert isinstance(devices_list, list)

    async def mock_http_call_failed(endpoint, method="GET", json_data=None):
        raise ConnectionError("Remote plugin is down")

    remote_proxy._http_call = mock_http_call_failed

    devices_list_2 = await runtime.service_registry.call("devices.list")
    assert isinstance(devices_list_2, list)

    await runtime.shutdown()
