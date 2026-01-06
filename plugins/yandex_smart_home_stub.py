"""
Плагин `yandex_smart_home_stub` — заглушка внешнего источника данных (Яндекс).

Этот плагин имитирует внешний сервис Яндекса для проверки интеграции.
Не содержит реального API, OAuth или сетевых запросов.

Функции:
- зарегистрировать сервисы для синхронизации и управления устройствами
- публиковать события об обнаружении устройств и изменении состояния
- не знать о конкретных доменах (только публиковать события)
"""

from __future__ import annotations

from typing import Any, Dict

from plugins.base_plugin import BasePlugin, PluginMetadata


class YandexSmartHomeStubPlugin(BasePlugin):
    """Заглушка для интеграции с Яндекс Умным Домом.

    Генерирует fake-устройства и публикует события,
    чтобы тестировать систему без реального API.
    """

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="yandex_smart_home",
            version="0.1.0",
            description="Заглушка для интеграции с Яндекс Умным Домом",
            author="Home Console",
        )

    async def on_load(self) -> None:
        """Загрузка: зарегистрировать сервисы."""
        await super().on_load()

        # Сервис 1: sync_devices() — генерирует и публикует fake-устройства
        async def _sync_devices() -> list[Dict[str, Any]]:
            """Синхронизировать устройства из Яндекса.

            Генерирует список fake-устройств и публикует события об их обнаружении.
            """
            devices = [
                {
                    "external_id": "yandex-light-kitchen",
                    "type": "light",
                    "capabilities": ["on_off", "brightness"],
                    "state": {"on": True, "brightness": 75},
                },
                {
                    "external_id": "yandex-light-bedroom",
                    "type": "light",
                    "capabilities": ["on_off"],
                    "state": {"on": False},
                },
                {
                    "external_id": "yandex-sensor-temp",
                    "type": "temperature_sensor",
                    "capabilities": ["temperature"],
                    "state": {"temperature": 22.5},
                },
            ]

            # Для каждого устройства публикуем событие обнаружения
            for device in devices:
                await self.runtime.event_bus.publish("external.device_discovered", {
                    "provider": "yandex",
                    "external_id": device["external_id"],
                    "type": device["type"],
                    "capabilities": device["capabilities"],
                    "state": device["state"],
                })

            return devices

        # Сервис 2: set_device_state() — обновляет состояние устройства
        async def _set_device_state(external_id: str, state: Dict[str, Any]) -> None:
            """Установить состояние устройства в Яндексе.

            Публикует событие об изменении состояния для подписчиков.
            """
            # Публикуем событие об изменении состояния
            await self.runtime.event_bus.publish("external.device_state_reported", {
                "provider": "yandex",
                "external_id": external_id,
                "type": "unknown",  # заглушка не знает точный тип
                "capabilities": [],
                "state": state,
            })

        # Регистрируем сервисы
        self.runtime.service_registry.register("yandex.sync_devices", _sync_devices)
        self.runtime.service_registry.register("yandex.set_device_state", _set_device_state)

    async def on_start(self) -> None:
        """Запуск: логируем инициализацию."""
        await super().on_start()
        
        # Пишем лог о запуске, если logger доступен
        try:
            await self.runtime.service_registry.call(
                "logger.log",
                level="info",
                message="yandex_smart_home_stub запущен",
                plugin=self.metadata.name,
            )
        except Exception:
            pass

    async def on_stop(self) -> None:
        """Остановка: ничего не делаем."""
        await super().on_stop()

    async def on_unload(self) -> None:
        """Выгрузка: удаляем сервисы."""
        await super().on_unload()
        
        # Удаляем зарегистрированные сервисы
        try:
            self.runtime.service_registry.unregister("yandex.sync_devices")
            self.runtime.service_registry.unregister("yandex.set_device_state")
        except Exception:
            pass
