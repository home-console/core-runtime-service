"""
Плагин `devices` — эталонный доменный плагин для хранения и управления устройствами.

Архитектурные принципы:
- Единственный источник истины: runtime.storage
- Плагин ТОЛЬКО пишет в storage, НИКОГДА не пишет в state_engine
- state_engine синхронизируется автоматически CoreRuntime через события
- Плагин НЕ знает про HTTP, UI, FastAPI, конкретные интеграции (Yandex и т.д.)

Контракт с Core:
- runtime.storage — для персистентности (используется)
- runtime.event_bus — для коммуникации между плагинами (используется)
- runtime.service_registry — для регистрации сервисов (используется)
- runtime.state_engine — только для чтения (НЕ используется)
"""

from typing import Any, Dict, List, Optional
import copy

from plugins.base_plugin import BasePlugin, PluginMetadata


class DevicesPlugin(BasePlugin):
    """Плагин для управления устройствами.

    Модель устройства (в storage):
      - id: str
      - name: str
      - type: str
      - state:
          desired: dict    # желаемое состояние (что хотим)
          reported: dict   # подтверждённое состояние от провайдера (что было)
          pending: bool    # ожидается ли подтверждение команды

    Поток данных:
    1. Плагин пишет в storage[devices]
    2. Storage публикует событие storage.updated
    3. CoreRuntime зеркалирует в state_engine (автоматически)
    4. UI/интеграции читают из state_engine
    """

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="devices",
            version="1.0.0",
            description="Плагин для хранения и управления устройствами",
            author="Home Console",
        )

    async def on_load(self) -> None:
        """Регистрация сервисов."""
        await super().on_load()
        
        # Основные сервисы для работы с устройствами
        self.runtime.service_registry.register("devices.list", self.list_devices)
        self.runtime.service_registry.register("devices.get", self.get_device)
        self.runtime.service_registry.register("devices.create", self.create_device)
        
        # Единственный способ изменить состояние устройства
        self.runtime.service_registry.register("devices.set_state", self.set_state)
        
        # Список внешних устройств
        self.runtime.service_registry.register("devices.list_external", self.list_external)
        
        # Mapping сервисы
        self.runtime.service_registry.register("devices.create_mapping", self.create_mapping)
        self.runtime.service_registry.register("devices.list_mappings", self.list_mappings)
        self.runtime.service_registry.register("devices.delete_mapping", self.delete_mapping)
        self.runtime.service_registry.register("devices.auto_map_external", self.auto_map_external)

    async def on_start(self) -> None:
        """Инициализация при старте: загрузка устройств и миграция состояния."""
        await super().on_start()
        
        try:
            keys = await self.runtime.storage.list_keys("devices")
        except Exception:
            return

        # Миграция legacy-состояний и восстановление read-model в state_engine
        for dev_id in keys:
            device = await self.runtime.storage.get("devices", dev_id)
            if device is None:
                continue
            
            state_value = device.get("state")
            
            # Миграция legacy-состояний → {desired, reported, pending}
            if not isinstance(state_value, dict) or \
               not all(k in state_value for k in ["desired", "reported", "pending"]):
                # Конвертируем старый формат в новый
                new_state = {
                    "desired": {},
                    "reported": {},
                    "pending": False
                }
                
                if isinstance(state_value, dict):
                    # Пытаемся восстановить данные из legacy-полей
                    if "power" in state_value:
                        power_val = state_value.get("power")
                        on_state = power_val in (True, "on", "true", 1, "1")
                        new_state["desired"]["on"] = on_state
                        new_state["reported"]["on"] = on_state
                    elif "on" in state_value:
                        on_state = bool(state_value.get("on"))
                        new_state["desired"]["on"] = on_state
                        new_state["reported"]["on"] = on_state
                
                # Если пусто, установим default
                if not new_state["desired"] and not new_state["reported"]:
                    new_state["desired"]["on"] = False
                    new_state["reported"]["on"] = False
                
                device["state"] = new_state
                try:
                    await self.runtime.storage.set("devices", dev_id, device)
                except Exception:
                    pass
        
        # Подписываемся на события от внешних провайдеров
        # Синхронизируем reported-состояние, когда провайдер подтверждает команду
        self._external_state_handler = self._handle_external_state
        try:
            self.runtime.event_bus.subscribe(
                "external.device_state_reported",
                self._external_state_handler
            )
        except Exception:
            pass

        # Подписываемся на обнаружение новых внешних устройств
        # Сохраняем их в storage для доступа через devices.list_external
        self._external_device_handler = self._handle_external_device_discovered
        try:
            self.runtime.event_bus.subscribe(
                "external.device_discovered",
                self._external_device_handler
            )
        except Exception:
            pass

    async def on_stop(self) -> None:
        """Остановка: отписка от событий."""
        await super().on_stop()
        try:
            handler = getattr(self, "_external_state_handler", None)
            if handler:
                self.runtime.event_bus.unsubscribe(
                    "external.device_state_reported",
                    handler
                )
        except Exception:
            pass
        try:
            handler = getattr(self, "_external_device_handler", None)
            if handler:
                self.runtime.event_bus.unsubscribe(
                    "external.device_discovered",
                    handler
                )
        except Exception:
            pass

    async def on_unload(self) -> None:
        """Выгрузка: удаление сервисов."""
        await super().on_unload()
        
        services = [
            "devices.list",
            "devices.get",
            "devices.create",
            "devices.set_state",
            "devices.list_external",
            "devices.create_mapping",
            "devices.list_mappings",
            "devices.delete_mapping",
            "devices.auto_map_external",
        ]
        
        for service in services:
            try:
                self.runtime.service_registry.unregister(service)
            except Exception:
                pass
        
        self.runtime = None

    # ========== СЕРВИСЫ ==========

    async def create_device(
        self,
        device_id: str,
        name: str = "Unknown",
        device_type: str = "generic"
    ) -> Dict[str, Any]:
        """Создать новое устройство.
        
        Модель состояния:
          state:
            desired: {}      — желаемое состояние
            reported: {}     — подтверждённое состояние
            pending: false   — ожидается ли подтверждение
        """
        if not isinstance(device_id, str) or not device_id:
            raise ValueError("device_id должен быть непустой строкой")

        device = {
            "id": device_id,
            "name": name,
            "type": device_type,
            "state": {
                "desired": {"on": False},
                "reported": {"on": False},
                "pending": False,
            },
        }
        
        # Только пишем в storage; state_engine обновится через события
        await self.runtime.storage.set("devices", device_id, device)
        
        return device

    async def set_state(self, device_id: str, state: Dict[str, Any]) -> Dict[str, Any]:
        """Установить желаемое состояние устройства (отправить команду).
        
        Этот метод:
        1. Читает устройство из storage
        2. Обновляет state.desired
        3. Устанавливает state.pending = True
        4. Сохраняет в storage
        5. Публикует событие internal.device_command_requested
        
        reported-состояние меняется ТОЛЬКО когда провайдер подтверждает команду
        через событие external.device_state_reported.
        """
        if not isinstance(device_id, str) or not device_id:
            raise ValueError("device_id должен быть непустой строкой")
        
        device = await self.runtime.storage.get("devices", device_id)
        if device is None:
            raise ValueError(f"device {device_id} not found")

        current_state = device.get("state", {})
        if not isinstance(current_state, dict):
            current_state = {"desired": {}, "reported": {}, "pending": False}

        # Ensure all fields exist
        for field in ["desired", "reported", "pending"]:
            if field not in current_state:
                current_state[field] = {} if field != "pending" else False

        # Обновляем only desired (это команда)
        if isinstance(state, dict):
            current_state["desired"].update(state)

        # Отмечаем, что команда ожидает подтверждения
        current_state["pending"] = True

        device["state"] = current_state
        
        # Пишем в storage; state_engine обновится через события
        await self.runtime.storage.set("devices", device_id, device)

        # Находим external_id для события (если этот device замаппирован)
        external_id = None
        try:
            keys = await self.runtime.storage.list_keys("devices_mappings")
            for k in keys:
                v = await self.runtime.storage.get("devices_mappings", k)
                if v == device_id:
                    external_id = k
                    break
        except Exception:
            pass

        # Публикуем событие о команде (не определяем provider — это ответственность интеграции)
        try:
            await self.runtime.event_bus.publish(
                "internal.device_command_requested",
                {
                    "internal_id": device_id,
                    "external_id": external_id,
                    "command": "set_state",
                    "params": state,
                }
            )
        except Exception:
            pass

        return {"ok": True, "queued": True, "external_id": external_id, "state": current_state}

    async def list_devices(self) -> List[Dict[str, Any]]:
        """Получить список всех устройств."""
        try:
            keys = await self.runtime.storage.list_keys("devices")
        except Exception:
            return []

        devices: List[Dict[str, Any]] = []
        for dev_id in keys:
            device = await self.runtime.storage.get("devices", dev_id)
            if device is not None:
                devices.append(device)
        
        return devices

    async def get_device(self, device_id: str) -> Dict[str, Any]:
        """Получить устройство по id."""
        if not isinstance(device_id, str) or not device_id:
            raise ValueError("device_id должен быть непустой строкой")

        device = await self.runtime.storage.get("devices", device_id)
        if device is None:
            raise ValueError(f"Устройство с id='{device_id}' не найдено")
        
        return device

    async def list_external(self, provider: Optional[str] = None) -> List[Dict[str, Any]]:
        """Получить список внешних устройств, опционально фильтруя по провайдеру."""
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

    async def create_mapping(
        self,
        external_id: str,
        internal_id: str
    ) -> Dict[str, Any]:
        """Создать маппинг между внешним и внутренним устройством."""
        if not external_id or not internal_id:
            raise ValueError("external_id и internal_id должны быть непустыми")

        # Пишем только в storage; state_engine обновится через события
        await self.runtime.storage.set("devices_mappings", external_id, internal_id)
        
        return {"ok": True, "external_id": external_id, "internal_id": internal_id}

    async def list_mappings(self) -> List[Dict[str, Any]]:
        """Получить список всех маппингов."""
        try:
            keys = await self.runtime.storage.list_keys("devices_mappings")
        except Exception:
            return []

        out: List[Dict[str, Any]] = []
        for k in keys:
            try:
                v = await self.runtime.storage.get("devices_mappings", k)
            except Exception:
                v = None
            if v is not None:
                out.append({"external_id": k, "internal_id": v})
        
        return out

    async def delete_mapping(self, external_id: str) -> Dict[str, Any]:
        """Удалить маппинг."""
        if not external_id:
            return {"ok": False, "error": "external_id required"}

        try:
            deleted = await self.runtime.storage.delete("devices_mappings", external_id)
        except Exception:
            deleted = False
        
        return {"ok": bool(deleted), "external_id": external_id}

    async def auto_map_external(self, provider: Optional[str] = None) -> Dict[str, Any]:
        """Автоматически создать internal devices для unmapped external устройств.
        
        Если provider задан, фильтрует по провайдеру, но НЕ встраивает его в internal_id.
        """
        created = 0
        skipped = 0
        errors: List[str] = []

        try:
            externals = await self.list_external(provider)
        except Exception as e:
            return {"ok": False, "error": f"failed_list_external: {e}"}

        for item in externals:
            ext_id = item.get("external_id")
            payload = item.get("payload", {})
            
            if not ext_id:
                continue

            # Проверяем, нет ли уже маппинга
            try:
                existing = await self.runtime.storage.get("devices_mappings", ext_id)
            except Exception:
                existing = None
            
            if existing:
                skipped += 1
                continue

            # Генерируем neutral internal_id (без привязки к провайдеру)
            internal_id = f"device-{ext_id}"
            name = None
            
            if isinstance(payload, dict):
                name = payload.get("name") or payload.get("title")
            
            if not name:
                device_type = payload.get("type", "device") if isinstance(payload, dict) else "device"
                name = f"{device_type} ({ext_id[:8]})"
            
            device_type = payload.get("type", "generic") if isinstance(payload, dict) else "generic"

            # Создаём internal device
            try:
                await self.create_device(internal_id, name, device_type)
            except Exception:
                # Попытаемся использовать существующий
                try:
                    dev = await self.runtime.storage.get("devices", internal_id)
                    if not dev:
                        raise
                except Exception as ce:
                    errors.append(f"create_failed:{ext_id}:{ce}")
                    continue

            # Создаём маппинг
            try:
                await self.runtime.storage.set("devices_mappings", ext_id, internal_id)
                created += 1
            except Exception as e:
                errors.append(f"mapping_failed:{ext_id}:{e}")

        return {"ok": True, "created": created, "skipped": skipped, "errors": errors}

    # ========== ОБРАБОТЧИКИ СОБЫТИЙ ==========

    async def _handle_external_device_discovered(self, event_type: str, data: dict) -> None:
        """Обработчик external.device_discovered.
        
        Сохраняет payload внешнего устройства для доступа через devices.list_external.
        """
        external_id = data.get("external_id")
        if not external_id:
            return

        # Сохраняем payload в storage для доступа через devices.list_external
        try:
            await self.runtime.storage.set("devices_external", external_id, data)
        except Exception:
            pass

    async def _handle_external_state(self, event_type: str, data: dict) -> None:
        """Обработчик external.device_state_reported.
        
        Когда провайдер подтверждает изменение состояния:
        1. Находим internal_id через маппинг
        2. Обновляем reported-состояние
        3. Сбрасываем pending-флаг
        4. Сохраняем в storage
        5. Публикуем internal.device_state_updated
        """
        external_id = data.get("external_id")
        reported_state = data.get("state")
        
        if not external_id or reported_state is None:
            return

        # Находим internal_id через маппинг
        try:
            internal_id = await self.runtime.storage.get("devices_mappings", external_id)
        except Exception:
            internal_id = None

        if not internal_id:
            return

        # Получаем device из storage
        try:
            device = await self.runtime.storage.get("devices", internal_id)
        except Exception:
            device = None

        if device is None:
            return

        # Обновляем состояние
        old_state = device.get("state", {})
        if not isinstance(old_state, dict):
            old_state = {"desired": {}, "reported": {}, "pending": False}

        # Ensure all fields
        for field in ["desired", "reported", "pending"]:
            if field not in old_state:
                old_state[field] = {} if field != "pending" else False

        # Сохраняем копию для события
        prev_state = copy.deepcopy(old_state)

        # Обновляем reported (то что вернул провайдер)
        if isinstance(reported_state, dict):
            old_state["reported"].update(reported_state)

        # Команда выполнена
        old_state["pending"] = False

        new_state = old_state

        # Сохраняем в storage
        device["state"] = new_state
        try:
            await self.runtime.storage.set("devices", internal_id, device)
        except Exception:
            pass

        # Публикуем событие об обновлении
        try:
            await self.runtime.event_bus.publish(
                "internal.device_state_updated",
                {
                    "internal_id": internal_id,
                    "external_id": external_id,
                    "old_state": prev_state,
                    "new_state": new_state,
                }
            )
        except Exception:
            pass
