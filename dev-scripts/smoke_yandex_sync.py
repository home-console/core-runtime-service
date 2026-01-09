"""Smoke runner: запуск CoreRuntime, загрузка yandex_smart_home_stub и вызов yandex.sync_devices

Это короткий сценарий для проверки цепочки: external → event_bus → devices
Файл временный — легко удаляется.
"""
import asyncio
from typing import Any, Dict, Optional

from core.runtime import CoreRuntime
from plugins.yandex_smart_home_stub import YandexSmartHomeStubPlugin
from modules.devices import register_devices


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

    runtime.event_bus.subscribe("external.device_discovered", _print_event)

    # Регистрируем встроенный модуль devices
    print("Registering devices module...")
    register_devices(runtime)

    plugin = YandexSmartHomeStubPlugin(runtime)
    print("Loading yandex plugin...")
    await runtime.plugin_manager.load_plugin(plugin)
    print("Starting yandex plugin...")
    await runtime.plugin_manager.start_plugin(plugin.metadata.name)

    # Вызов сервиса sync_devices
    print("Calling yandex.sync_devices service...")
    devices = await runtime.service_registry.call("yandex.sync_devices")
    print("Returned devices:")
    print(devices)

    # --- Временный smoke-вызов: проверить devices.map_external_device ---
    # Берём первый внешний device (если есть) и сопоставляем с тестовым internal_id
    if devices:
        first = devices[0]
        external_id = first.get("external_id")
        if external_id:
            test_internal_id = "internal-test-123"
            print(f"Calling devices.map_external_device for {external_id} -> {test_internal_id}")
            await runtime.service_registry.call("devices.map_external_device", external_id, test_internal_id)

            # Проверяем, что mapping сохранился в state_engine
            stored = await runtime.state_engine.get(f"devices.mapping.{external_id}")
            print(f"Mapping stored in state_engine: devices.mapping.{external_id} = {stored}")

    # Дать немного времени на обработку событий
    await asyncio.sleep(0.5)

    # Остановить и выгрузить плагины (в обратном порядке)
    print("Stopping yandex plugin...")
    await runtime.plugin_manager.stop_plugin(plugin.metadata.name)
    print("Unloading yandex plugin...")
    await runtime.plugin_manager.unload_plugin(plugin.metadata.name)

    # devices module is built-in; no plugin stop/unload required

    # Закрыть storage
    await runtime.storage.close()


if __name__ == "__main__":
    asyncio.run(main())
