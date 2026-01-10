"""
Smoke runner: запуск CoreRuntime, загрузка yandex_smart_home_real и вызов yandex.sync_devices

Этот тест:
1. Создаёт RuntimeyWithMockOAuth
2. Регистрирует mock oauth_yandex.get_tokens (возвращает fake access_token)
3. Mock-ит aiohttp для вернёния fake Яндекс API response
4. Загружает real plugin
5. Вызывает yandex.sync_devices и проверяет результаты

Файл временный — легко удаляется.
"""
import asyncio
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

from core.runtime import CoreRuntime
from plugins.yandex_smart_home import YandexSmartHomeRealPlugin
from modules import DevicesModule
from plugins.test import SystemLoggerPlugin


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


# Mock Яндекс API response
YANDEX_MOCK_RESPONSE = {
    "devices": [
        {
            "id": "yandex-light-kitchen",
            "name": "Свет кухни",
            "type": "devices.types.light",
            "capabilities": [
                {
                    "type": "devices.capabilities.on_off",
                    "retrievable": True,
                    "reportable": True,
                },
                {
                    "type": "devices.capabilities.range",
                    "retrievable": True,
                    "reportable": True,
                    "parameters": {
                        "instance": "brightness",
                        "range": {"min": 0, "max": 100}
                    }
                }
            ],
            "states": [
                {
                    "type": "devices.capabilities.on_off",
                    "state": {
                        "instance": "on",
                        "value": True
                    }
                },
                {
                    "type": "devices.capabilities.range",
                    "state": {
                        "instance": "brightness",
                        "value": 75
                    }
                }
            ]
        },
        {
            "id": "yandex-light-bedroom",
            "name": "Свет спальни",
            "type": "devices.types.light",
            "capabilities": [
                {
                    "type": "devices.capabilities.on_off",
                    "retrievable": True,
                    "reportable": True,
                }
            ],
            "states": [
                {
                    "type": "devices.capabilities.on_off",
                    "state": {
                        "instance": "on",
                        "value": False
                    }
                }
            ]
        },
        {
            "id": "yandex-sensor-temp",
            "name": "Датчик температуры",
            "type": "devices.types.sensor.climate",
            "capabilities": [
                {
                    "type": "devices.capabilities.range",
                    "retrievable": True,
                    "reportable": True,
                    "parameters": {
                        "instance": "temperature",
                        "unit": "unit.temperature.celsius",
                        "range": {"min": -50, "max": 50}
                    }
                }
            ],
            "states": [
                {
                    "type": "devices.capabilities.range",
                    "state": {
                        "instance": "temperature",
                        "value": 22.5
                    }
                }
            ]
        }
    ]
}


class MockAsyncContextManager:
    """Mock для aiohttp.ClientSession.get() context manager."""
    def __init__(self, response):
        self.response = response
    
    async def __aenter__(self):
        return self.response
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


def mock_aiohttp_get(url, headers, timeout):
    """Mock для aiohttp.ClientSession.get()."""
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=YANDEX_MOCK_RESPONSE)
    mock_resp.text = AsyncMock(return_value="OK")
    
    return MockAsyncContextManager(mock_resp)


async def main():
    print("=== Smoke Test: yandex_smart_home_real ===\n")

    storage = SimpleMemoryStorage()
    runtime = CoreRuntime(storage)

    # Счётчик событий
    events_received = []

    async def _on_device_discovered(event_type: str, data: dict):
        print(f"[EVENT] {event_type}")
        print(f"  provider: {data.get('provider')}")
        print(f"  external_id: {data.get('external_id')}")
        print(f"  type: {data.get('type')}")
        print(f"  capabilities: {data.get('capabilities')}")
        print(f"  state: {data.get('state')}\n")
        events_received.append(data)

    await runtime.event_bus.subscribe("external.device_discovered", _on_device_discovered)

    # Загрузить logger
    logger_plugin = SystemLoggerPlugin(runtime)
    print("Loading system_logger plugin...")
    await runtime.plugin_manager.load_plugin(logger_plugin)
    await runtime.plugin_manager.start_plugin(logger_plugin.metadata.name)

    # Register devices module instead of loading plugin
    print("Registering devices module...")
    devices_module = DevicesModule(runtime)
    await runtime.module_manager.register(devices_module)

    # Регистрируем mock oauth_yandex.get_tokens
    async def mock_get_tokens():
        print("[MOCK] oauth_yandex.get_tokens called, returning fake access_token")
        return {
            "access_token": "fake_access_token_12345",
            "token_type": "Bearer",
            "expires_in": 3600,
        }

    await runtime.service_registry.register("oauth_yandex.get_tokens", mock_get_tokens)

    # Загрузить real plugin
    real_plugin = YandexSmartHomeRealPlugin(runtime)
    print("Loading yandex_smart_home_real plugin...")
    await runtime.plugin_manager.load_plugin(real_plugin)
    print("Starting yandex_smart_home_real plugin...")
    await runtime.plugin_manager.start_plugin(real_plugin.metadata.name)

    # Вызов сервиса sync_devices с mock aiohttp
    print("\nCalling yandex.sync_devices with mocked aiohttp...\n")
    
    # Patch aiohttp.ClientSession
    with patch("aiohttp.ClientSession") as mock_session_class:
        mock_session = MagicMock()
        mock_session_class.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_class.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_session.get = mock_aiohttp_get
        
        try:
            devices = await runtime.service_registry.call("yandex.sync_devices")
            print(f"\n✓ sync_devices returned {len(devices)} devices")
            print(f"✓ {len(events_received)} events received\n")
            
            # Проверка совместимости со stub-плагином
            print("=== Compatibility Check ===\n")
            for device in devices:
                assert device.get("provider") == "yandex", f"provider должен быть 'yandex', получено: {device.get('provider')}"
                assert "external_id" in device, "external_id обязателен"
                assert "type" in device, "type обязателен"
                assert "capabilities" in device, "capabilities обязателены"
                assert "state" in device, "state обязателен"
            
            print("✓ All devices have required fields")
            print("✓ Format is identical to stub-plugin\n")
            
            # Проверка трансформации типов и capabilities
            print("=== Device Transformation Check ===\n")
            for device in devices:
                external_id = device.get("external_id")
                device_type = device.get("type")
                capabilities = device.get("capabilities")
                state = device.get("state")
                
                print(f"Device: {external_id}")
                print(f"  Type: {device_type}")
                print(f"  Capabilities: {capabilities}")
                print(f"  State: {state}\n")
            
            assert len(devices) == 3, f"Expected 3 devices, got {len(devices)}"
            
            # Проверка первого устройства (свет с brightness)
            light_kitchen = devices[0]
            assert light_kitchen["external_id"] == "yandex-light-kitchen"
            assert light_kitchen["type"] == "light"
            assert "on_off" in light_kitchen["capabilities"]
            assert "range" in light_kitchen["capabilities"]
            assert light_kitchen["state"]["on"] == True
            assert light_kitchen["state"]["range"] == 75
            
            # Проверка второго устройства (свет без brightness)
            light_bedroom = devices[1]
            assert light_bedroom["external_id"] == "yandex-light-bedroom"
            assert light_bedroom["type"] == "light"
            assert light_bedroom["state"]["on"] == False
            
            # Проверка датчика
            sensor_temp = devices[2]
            assert sensor_temp["external_id"] == "yandex-sensor-temp"
            assert sensor_temp["type"] == "climate"  # devices.types.sensor.climate -> climate
            assert "range" in sensor_temp["capabilities"]
            assert sensor_temp["state"]["range"] == 22.5
            
            print("✓ All assertions passed!\n")

        except Exception as e:
            print(f"\n✗ Error: {e}")
            import traceback
            traceback.print_exc()

    # Остановить и выгрузить
    print("Stopping plugins...")
    await runtime.plugin_manager.stop_plugin(real_plugin.metadata.name)
    await runtime.plugin_manager.unload_plugin(real_plugin.metadata.name)

    # devices module is built-in; no plugin stop/unload required

    await runtime.plugin_manager.stop_plugin(logger_plugin.metadata.name)
    await runtime.plugin_manager.unload_plugin(logger_plugin.metadata.name)

    await runtime.storage.close()

    print("=== Test Complete ===")


if __name__ == "__main__":
    asyncio.run(main())
