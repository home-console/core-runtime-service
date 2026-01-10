"""Smoke runner: запуск CoreRuntime, загрузка yandex_smart_home_stub и вызов yandex.sync_devices

- Временный скрипт для локальной проверки
- Не меняет архитектуру, легко удаляется
"""
import asyncio
import sys
from typing import Any, Dict, Optional

# Настроить sys.path чтобы корректно импортировать package
ROOT = __file__

from core.runtime import CoreRuntime
from plugins.test import YandexSmartHomeStubPlugin


class SimpleMemoryStorage:
    def __init__(self):
        self._data: Dict[str, Dict[str, Dict[str, Any]]] = {}

    async def get(self, namespace: str, key: str) -> Optional[dict]:
        return self._data.get(namespace, {}).get(key)

    async def set(self, namespace: str, key: str, value: dict) -> None:
        self._data.setdefault(namespace, {})[key] = value

    async def delete(self, namespace: str, key: str) -> bool:
        ns = self._data.get(namespace, {})
        if key in ns:
            del ns[key]
            return True
        return False

    async def list_keys(self, namespace: str) -> list:
        return list(self._data.get(namespace, {}).keys())

    async def clear_namespace(self, namespace: str) -> None:
        self._data.pop(namespace, None)

    async def close(self) -> None:
        pass


async def main():
    storage = SimpleMemoryStorage()
    runtime = CoreRuntime(storage)

    # Подписчик для показа событий в консоли
    async def _print_event(event_type: str, data: dict):
        print(f"[EVENT] {event_type}: {data}")

    await runtime.event_bus.subscribe("external.device_discovered", _print_event)

    # Создать и загрузить плагин
    plugin = YandexSmartHomeStubPlugin(runtime)
    print("Loading plugin...")
    await runtime.plugin_manager.load_plugin(plugin)
    print("Starting plugin...")
    await runtime.plugin_manager.start_plugin(plugin.metadata.name)

    # Вызов сервиса sync_devices
    print("Calling yandex.sync_devices service...")
    devices = await runtime.service_registry.call("yandex.sync_devices")
    print("Returned devices:")
    print(devices)

    # Дать немного времени на обработку событий
    await asyncio.sleep(0.5)

    # Остановить и выгрузить плагин
    print("Stopping plugin...")
    await runtime.plugin_manager.stop_plugin(plugin.metadata.name)
    print("Unloading plugin...")
    await runtime.plugin_manager.unload_plugin(plugin.metadata.name)

    # Закрыть storage
    await runtime.storage.close()


if __name__ == "__main__":
    asyncio.run(main())
