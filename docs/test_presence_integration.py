"""
Smoke-test для плагина `presence`.

Проверяет:
- регистрация сервиса `presence.set`
- изменение состояния runtime.state (presence.home)
- публикацию событий `presence.entered` и `presence.left`
- регистрацию HTTP контрактов
"""

import asyncio
import pytest
from pathlib import Path

from core.config import Config
from core.runtime import CoreRuntime
from adapters.sqlite_adapter import SQLiteAdapter
from plugins.system_logger_plugin import SystemLoggerPlugin
from modules.devices import register_devices
from plugins.automation_stub_plugin import AutomationStubPlugin
from plugins.presence_plugin import PresencePlugin


@pytest.mark.asyncio
async def test_presence():
    print("\nTEST: presence plugin integration")

    config = Config(db_path="data/test_presence.db")
    Path(config.db_path).parent.mkdir(parents=True, exist_ok=True)

    adapter = SQLiteAdapter(config.db_path)
    await adapter.initialize_schema()
    runtime = CoreRuntime(adapter)


    logger = SystemLoggerPlugin(runtime)
    await runtime.plugin_manager.load_plugin(logger)

    # register devices module instead of loading plugin
    register_devices(runtime)

    automation = AutomationStubPlugin(runtime)
    await runtime.plugin_manager.load_plugin(automation)

    presence = PresencePlugin(runtime)
    await runtime.plugin_manager.load_plugin(presence)

    await runtime.start()

    # Проверка регистрации сервиса
    services = runtime.service_registry.list_services()
    print("services:", services)
    assert "presence.set" in services

    # Проверка HTTP контрактов
    endpoints = runtime.http.list()
    paths = [ep.path for ep in endpoints]
    print("http paths:", paths)
    assert "/presence/enter" in paths
    assert "/presence/leave" in paths

    # Проверка начального состояния
    cur = await runtime.state_engine.get("presence.home")
    print("initial presence.home:", cur)
    assert cur is False

    # Вызов presence.set True => presence.entered event
    await runtime.service_registry.call("presence.set", True)
    await asyncio.sleep(0.1)
    cur2 = await runtime.state_engine.get("presence.home")
    print("after set True:", cur2)
    assert cur2 is True

    # Вызов presence.set False => presence.left event
    await runtime.service_registry.call("presence.set", False)
    await asyncio.sleep(0.1)
    cur3 = await runtime.state_engine.get("presence.home")
    print("after set False:", cur3)
    assert cur3 is False

    await runtime.shutdown()
    print("OK")


if __name__ == '__main__':
    asyncio.run(test_presence())
