"""
Плагин `devices` — эталонный доменный плагин для хранения и управления устройствами.

Контракт с Core: доступ к `runtime.storage`, `runtime.state_engine`,
`runtime.event_bus`, `runtime.service_registry` через `self.runtime`.

Всё взаимодействие с данными идёт через эти API — плагин не знает про БД,
адаптеры или другие плагины.
"""

# Пояснение по границе ответственности:
# - "devices" (постфикс в storage/state) — это доменные устройства, которыми
#   управляет система (внутренние сущности). Они сохраняются в `storage`
#   под namespace "devices" и их состояние отражается в `state_engine`
#   по ключам вида `device.<id>`.
# - "devices.external.*" — это сырые payload'ы внешних интеграций (например,
#   события от провайдеров). Эти записи НЕ считаются доменными устройствами и
#   не должны автоматически маппиться или преобразовываться. Они хранятся
#   в `state_engine` как вспомогательные данные интеграции и отделены по
#   пространству имён (ключи `devices.external.<external_id>`).


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
        # Универсальное изменение состояния
        self.runtime.service_registry.register("devices.set_state", self.set_state)
        # Сохраним старые удобные вызовы для обратной совместимости
        self.runtime.service_registry.register("devices.turn_on", self.turn_on)
        self.runtime.service_registry.register("devices.turn_off", self.turn_off)
        # Список внешних устройств от провайдеров
        self.runtime.service_registry.register("devices.list_external", self.list_external)
        # Временный сервис для сопоставления внешнего устройства с внутренним id
        # Сохраняет соответствие в runtime.state_engine по ключу
        # "devices.mapping.<external_id>" -> internal_id
        # Этот сервис НЕ создаёт internal устройство и НЕ копирует payload.
        async def _map_external_device(external_id: str, internal_id: str) -> None:
            """Сохранить mapping внешнего устройства.

            Ограничения:
            - не создавать internal device
            - не копировать payload
            - только сохраняет соответствие в state_engine
            """
            if not external_id or not internal_id:
                raise ValueError("external_id и internal_id должны быть непустыми строками")

            try:
                # Сохраняем маппинг и в persistent storage для долговечности
                await self.runtime.state_engine.set(f"devices.mapping.{external_id}", internal_id)
                try:
                    await self.runtime.storage.set("devices_mappings", external_id, internal_id)
                except Exception:
                    # Не фатально, оставляем в state_engine
                    pass
            except Exception:
                # Не мешаем основной логике плагина при ошибке записи
                raise

        self.runtime.service_registry.register("devices.map_external_device", _map_external_device)
        # Регистрируем HTTP-контракты через runtime.http
        # Devices plugin не регистрирует публичные admin HTTP-эндпоинты —
        # за это отвечает admin_plugin (прокси). Оставляем регистрацию пустой.
        try:
            pass
        except Exception:
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

        # Инициализируем external devices и mappings из storage, если есть
        try:
            ext_keys = await self.runtime.storage.list_keys("devices_external")
        except Exception:
            ext_keys = []

        for ext_id in ext_keys:
            payload = await self.runtime.storage.get("devices_external", ext_id)
            if payload is None:
                continue
            # Дублируем в state_engine для быстрого доступа
            try:
                await self.runtime.state_engine.set(f"devices.external.{ext_id}", payload)
            except Exception:
                pass

        # Загружаем маппинги в state_engine (если они были персистированы)
        try:
            map_keys = await self.runtime.storage.list_keys("devices_mappings")
        except Exception:
            map_keys = []

        for k in map_keys:
            try:
                internal = await self.runtime.storage.get("devices_mappings", k)
                if internal is not None:
                    await self.runtime.state_engine.set(f"devices.mapping.{k}", internal)
            except Exception:
                pass

        # --- Временная поддержка внешних устройств ---
        # Подписываемся на событие внешнего провайдера о найденном устройстве
        # Сохраняем payload в runtime.state_engine под ключом
        # "devices.external.<external_id>" и логируем факт приёма.
        async def _external_device_handler(event_type: str, data: dict):
            # Извлекаем external_id из payload
            external_id = data.get("external_id")
            if not external_id:
                return

            # Сохраняем payload и в persistent storage для внешних устройств
            try:
                await self.runtime.storage.set("devices_external", external_id, data)
            except Exception:
                pass

            # Также дублируем в state_engine для быстрого доступа
            try:
                await self.runtime.state_engine.set(f"devices.external.{external_id}", data)
            except Exception:
                pass

            # Логируем приём устройства через logger, если он доступен
            try:
                await self.runtime.service_registry.call(
                    "logger.log",
                    level="info",
                    message=f"External device accepted: {external_id}",
                    plugin=self.metadata.name,
                    context={"payload": data},
                )
            except Exception:
                pass

        # Сохранить хендлер для последующей отписки
        self._external_device_handler = _external_device_handler
        try:
            self.runtime.event_bus.subscribe("external.device_discovered", self._external_device_handler)
        except Exception:
            # Подписка вспомогательная — не должна ломать старый функционал
            pass

    async def on_stop(self) -> None:
        """Остановка плагина: не удаляем данные, не очищаем storage."""
        await super().on_stop()
        # Удаляем временную подписку на external.device_discovered
        try:
            handler = getattr(self, "_external_device_handler", None)
            if handler:
                self.runtime.event_bus.unsubscribe("external.device_discovered", handler)
        except Exception:
            pass

    async def on_unload(self) -> None:
        """Выгрузка плагина: удаляем сервисы и очищаем ссылки на runtime."""
        await super().on_unload()
        # Удаляем сервисы
        self.runtime.service_registry.unregister("devices.list")
        self.runtime.service_registry.unregister("devices.get")
        self.runtime.service_registry.unregister("devices.create")
        self.runtime.service_registry.unregister("devices.turn_on")
        self.runtime.service_registry.unregister("devices.turn_off")
        # Удаляем временный сервис mapping
        try:
            self.runtime.service_registry.unregister("devices.map_external_device")
        except Exception:
            pass

        # Очистить ссылку на runtime
        self.runtime = None

    # ----- Сервисы -----
    async def create_device(self, device_id: str, name: str = "Unknown", device_type: str = "generic") -> Dict[str, Any]:
        """Создать новое устройство.

        try:
            self.runtime.service_registry.unregister("devices.list")
            self.runtime.service_registry.unregister("devices.get")
            self.runtime.service_registry.unregister("devices.create")
        except Exception:
            pass
        # Универсальные и совместимые сервисы
        try:
            self.runtime.service_registry.unregister("devices.set_state")
        except Exception:
            pass
        try:
            self.runtime.service_registry.unregister("devices.turn_on")
        except Exception:
            pass
        try:
            self.runtime.service_registry.unregister("devices.turn_off")
        except Exception:
            pass
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

    async def set_state(self, device_id: str, state: Dict[str, Any]) -> Dict[str, Any]:
        """Установить состояние устройства полностью или частично.

        Аргументы:
            device_id: id внутреннего устройства
            state: частичное или полное состояние (словать)

        Поведение: обновляет storage и state_engine, публикует событие.
        """
        return await self._change_state(device_id, state)

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

    async def list_external(self, provider: Optional[str] = None) -> List[Dict[str, Any]]:
        """Вернуть список внешних устройств, опционально фильтруя по провайдеру.

        Хранение внешних устройств осуществляется в storage namespace `devices_external`.
        """
        try:
            keys = await self.runtime.storage.list_keys("devices_external")
        except Exception:
            return []

        out: List[Dict[str, Any]] = []
        for ext_id in keys:
            payload = await self.runtime.storage.get("devices_external", ext_id)
            if payload is None:
                continue
            if provider is not None:
                if payload.get("provider") != provider:
                    continue
            out.append({"external_id": ext_id, "payload": payload})
        return out

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
