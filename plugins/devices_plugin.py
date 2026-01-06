"""
Плагин `devices` — эталонный доменный плагин для хранения и управления устройствами.

Контракт с Core: доступ к `runtime.storage`, `runtime.state_engine`,
`runtime.event_bus`, `runtime.service_registry` через `self.runtime`.

Всё взаимодействие с данными идёт через эти API — плагин не знает про БД,
адаптеры или другие плагины.
"""

from typing import Any, Dict, List, Optional

from core.http_registry import HttpEndpoint
from plugins.base_plugin import BasePlugin, PluginMetadata


class DevicesPlugin(BasePlugin):
    """Плагин для управления устройствами.

    Модель устройства (внутренняя для плагина):
      - id: str
      - name: str
      - type: str
      - state: dict
    """

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="devices",
            version="0.1.0",
            description="Плагин для хранения и управления устройствами",
            author="Home Console",
        )

    async def on_load(self) -> None:
        """Сохранить runtime и зарегистрировать сервисы.

        Не выполнять тяжёлых операций здесь.
        """
        await super().on_load()
        # Регистрируем сервисы
        self.runtime.service_registry.register("devices.list", self.list_devices)
        self.runtime.service_registry.register("devices.get", self.get_device)
        self.runtime.service_registry.register("devices.create", self.create_device)
        self.runtime.service_registry.register("devices.turn_on", self.turn_on)
        self.runtime.service_registry.register("devices.turn_off", self.turn_off)
        # Регистрируем HTTP-контракты через runtime.http
        try:
            self.runtime.http.register(HttpEndpoint(method="GET", path="/devices", service="devices.list"))
            self.runtime.http.register(HttpEndpoint(method="POST", path="/devices", service="devices.create"))
            self.runtime.http.register(HttpEndpoint(method="POST", path="/devices/{device_id}/on", service="devices.turn_on"))
        except Exception:
            # любые ошибки регистрации контрактов не должны блокировать загрузку плагина
            pass

    async def on_start(self) -> None:
        """Инициализация runtime-state для устройств при старте.

        Загружает список устройств из персистентного хранилища и выставляет
        текущее состояние в `runtime.state_engine` ключи вида `device.{id}`.
        """
        await super().on_start()
        # Инициализируем состояние для всех устройств (не удаляем данные)
        try:
            keys = await self.runtime.storage.list_keys("devices")
        except Exception:
            # Если storage недоступен — ничего не делаем на старте
            return

        for dev_id in keys:
            device = await self.runtime.storage.get("devices", dev_id)
            if device is None:
                continue
            state_value = device.get("state")
            await self.runtime.state_engine.set(f"device.{dev_id}", state_value)

    async def on_stop(self) -> None:
        """Остановка плагина: не удаляем данные, не очищаем storage."""
        await super().on_stop()

    async def on_unload(self) -> None:
        """Выгрузка плагина: удаляем сервисы и очищаем ссылки на runtime."""
        await super().on_unload()
        # Удаляем сервисы
        self.runtime.service_registry.unregister("devices.list")
        self.runtime.service_registry.unregister("devices.get")
        self.runtime.service_registry.unregister("devices.create")
        self.runtime.service_registry.unregister("devices.turn_on")
        self.runtime.service_registry.unregister("devices.turn_off")

        # Очистить ссылку на runtime
        self.runtime = None

    # ----- Сервисы -----
    async def create_device(self, device_id: str, name: str = "Unknown", device_type: str = "generic") -> Dict[str, Any]:
        """Создать новое устройство.

        Args:
            device_id: уникальный идентификатор устройства
            name: человеческое имя устройства
            device_type: тип устройства

        Returns:
            Созданное устройство

        Raises:
            ValueError: если device_id не строка или пуста
        """
        if not isinstance(device_id, str) or not device_id:
            raise ValueError("device_id должен быть непустой строкой")

        device = {
            "id": device_id,
            "name": name,
            "type": device_type,
            "state": {"power": "off"},
        }
        await self.runtime.storage.set("devices", device_id, device)
        await self.runtime.state_engine.set(f"device.{device_id}", device["state"])
        return device

    # ----- Сервисы -----
    async def list_devices(self) -> List[Dict[str, Any]]:
        """Вернуть список всех устройств.

        Возвращает список словарей устройств, сохранённых в storage.
        """
        keys = await self.runtime.storage.list_keys("devices")
        devices: List[Dict[str, Any]] = []
        for dev_id in keys:
            device = await self.runtime.storage.get("devices", dev_id)
            if device is not None:
                devices.append(device)
        return devices

    async def get_device(self, device_id: str) -> Dict[str, Any]:
        """Вернуть устройство по id.

        Raises:
            ValueError: если `device_id` не строка или устройство не найдено
        """
        if not isinstance(device_id, str) or not device_id:
            raise ValueError("device_id должен быть непустой строкой")

        device = await self.runtime.storage.get("devices", device_id)
        if device is None:
            raise ValueError(f"Устройство с id='{device_id}' не найдено")
        return device

    async def turn_on(self, device_id: str) -> Dict[str, Any]:
        """Установить состояние устройства в 'on' и опубликовать событие.

        Возвращает обновлённое представление устройства.
        """
        return await self._change_state(device_id, {"power": "on"})

    async def turn_off(self, device_id: str) -> Dict[str, Any]:
        """Установить состояние устройства в 'off' и опубликовать событие.

        Возвращает обновлённое представление устройства.
        """
        return await self._change_state(device_id, {"power": "off"})

    # ----- Внутренние методы -----
    async def _change_state(self, device_id: str, new_state_partial: Dict[str, Any]) -> Dict[str, Any]:
        """Внутренняя логика изменения состояния устройства.

        Обновляет персистентное представление и текущее состояние в state engine,
        публикует событие `devices.state_changed`.
        """
        if not isinstance(device_id, str) or not device_id:
            raise ValueError("device_id должен быть непустой строкой")

        device = await self.runtime.storage.get("devices", device_id)
        if device is None:
            raise ValueError(f"Устройство с id='{device_id}' не найдено")

        old_state = device.get("state", {})
        # Создаём копию состояния и обновляем частично
        new_state = dict(old_state) if isinstance(old_state, dict) else {}
        new_state.update(new_state_partial)

        # Сохраняем в persistent storage
        device["state"] = new_state
        await self.runtime.storage.set("devices", device_id, device)

        # Обновляем runtime.state
        await self.runtime.state_engine.set(f"device.{device_id}", new_state)

        # Публикуем событие об изменении состояния
        await self.runtime.event_bus.publish("devices.state_changed", {
            "device_id": device_id,
            "old_state": old_state,
            "new_state": new_state,
        })

        return device
