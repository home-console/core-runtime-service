"""
Плагин `yandex_smart_home_real_v0` — синхронизация реальных устройств Яндекса.

Назначение:
- получить устройства из реального API Яндекса
- преобразовать их в стандартный формат
- опубликовать события об обнаружении устройств

Архитектура:
- plugin-first, in-process
- получает токены через oauth_yandex.get_tokens()
- НЕ хранит токены (берёт из oauth_yandex)
- НЕ знает OAuth деталей
- публикует ТОЛЬКО internal.device_discovered события
- полностью совместим со stub-плагином

Ограничения:
- НЕ управляет устройствами (нет set_device_state)
- НЕ интегрирует Алису
- НЕ делает refresh token
- НЕ делает retry / polling
- НЕ публикует другие события

Комментарии на русском языке.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from plugins.base_plugin import BasePlugin, PluginMetadata


class YandexSmartHomeRealPlugin(BasePlugin):
    """Синхронизирует реальные устройства из API Яндекса.

    Получает доступ к токенам только через:
    - runtime.service_registry.call("oauth_yandex.get_tokens")

    Публикует события:
    - external.device_discovered для каждого полученного устройства

    Взаимодействует только через:
    - event_bus (публикация событий)
    - service_registry (получение токенов, регистрация сервиса)
    - state_engine / storage (не требуется для первой версии)
    """

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="yandex_smart_home_real",
            version="0.1.0",
            description="Синхронизация реальных устройств из API Яндекса",
            author="Home Console",
        )

    async def on_load(self) -> None:
        """Загрузка: регистрируем сервис yandex.sync_devices()."""
        await super().on_load()

        async def _sync_devices() -> list[Dict[str, Any]]:
            """Синхронизировать устройства из реального API Яндекса.

            Этапы:
            1. Получить токены из oauth_yandex.get_tokens()
            2. Выполнить HTTP GET к https://api.iot.yandex.net/v1.0/user/info
            3. Преобразовать каждое устройство в стандартный формат
            4. Опубликовать external.device_discovered для каждого
            5. Вернуть список преобразованных устройств

            Возвращает:
                Список устройств в стандартном формате

            Throws:
                ValueError: если токены недоступны
                RuntimeError: если запрос к API не удался
            """
            # Feature flag: check storage key `yandex.use_real_api`
            try:
                use_real = await self.runtime.storage.get("yandex", "use_real_api")
            except Exception:
                use_real = False

            if not use_real:
                # Not enabled — signal to caller that real API is disabled
                raise RuntimeError("use_real_api_disabled")

            # ЭТАП 1: Проверить статус OAuth через oauth_yandex.get_status()
            try:
                status = await self.runtime.service_registry.call("oauth_yandex.get_status")
            except Exception as e:
                raise RuntimeError(f"Ошибка получения статуса oauth_yandex: {e}")

            if not status or not status.get("authorized"):
                # Explicitly signal unauthorized — caller should NOT fallback
                raise RuntimeError("yandex_not_authorized")

            # Получить токены
            try:
                tokens = await self.runtime.service_registry.call("oauth_yandex.get_tokens")
            except Exception as e:
                raise RuntimeError(f"Ошибка получения токенов от oauth_yandex: {e}")

            # Проверка: есть ли токены и access_token?
            if not tokens or "access_token" not in tokens:
                raise RuntimeError("yandex_not_authorized")

            access_token = tokens["access_token"]

            # ЭТАП 2: Выполнить HTTP запрос к Яндекс API
            try:
                import aiohttp
            except ImportError:
                raise RuntimeError("Требуется установить aiohttp для синхронизации устройств")

            # Real API endpoint
            url = "https://api.iot.yandex.net/v1.0/user/info"
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status != 200:
                            text = await resp.text()
                            raise RuntimeError(
                                f"Ошибка Яндекс API: HTTP {resp.status} — {text}"
                            )
                        api_response = await resp.json()
            except aiohttp.ClientError as e:
                raise RuntimeError(f"Сетевая ошибка при запросе к Яндекс API: {e}")

            # ЭТАП 3-4: Преобразовать устройства и опубликовать события
            devices = []

            # Структура ответа Яндекса: {"devices": [...]}
            # Some versions return list directly or under 'devices'
            if isinstance(api_response, dict) and "devices" in api_response:
                yandex_devices = api_response.get("devices", [])
            elif isinstance(api_response, list):
                yandex_devices = api_response
            else:
                yandex_devices = []

            for yandex_device in yandex_devices:
                # Преобразуем устройство в стандартный формат
                device = await self._transform_device(yandex_device)

                if device:
                    devices.append(device)

                    # Публикуем событие обнаружения (КРИТИЧЕСКИ: именно это событие)
                    try:
                        await self.runtime.event_bus.publish(
                            "external.device_discovered",
                            device
                        )
                    except Exception as e:
                        # Ошибка публикации одного устройства не должна блокировать остальные
                        # Логируем и продолжаем
                        try:
                            await self.runtime.service_registry.call(
                                "logger.log",
                                level="warning",
                                message=f"Ошибка публикации события для устройства {device.get('external_id')}: {e}",
                                plugin=self.metadata.name,
                            )
                        except Exception:
                            pass

            return devices

        # Регистрируем сервис
        self.runtime.service_registry.register("yandex.sync_devices", _sync_devices)

    async def _transform_device(self, yandex_device: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Преобразовать устройство из API Яндекса в стандартный формат.

        Структура входного устройства Яндекса:
        {
            "id": "...",
            "name": "...",
            "type": "devices.types.light",
            "capabilities": [...],
            "properties": [...],
            "states": [...]
        }

        Структура выходного формата (идентична stub):
        {
            "provider": "yandex",
            "external_id": "<id>",
            "type": "<light | switch | sensor | ...>",
            "capabilities": ["on_off", "brightness", ...],
            "state": { ... }
        }

        Args:
            yandex_device: устройство из ответа API Яндекса

        Returns:
            Преобразованное устройство или None если преобразование невозможно
        """
        try:
            # Получаем ID устройства (стабильный идентификатор)
            device_id = yandex_device.get("id")
            if not device_id:
                return None
            # Попробуем взять понятное имя устройства из ответа Яндекса
            # API обычно содержит поле "name" или "title"; используем сначала его
            name = yandex_device.get("name") or yandex_device.get("title") or device_id

            # Получаем тип устройства (формат: devices.types.light)
            yandex_type = yandex_device.get("type", "")

            # Извлекаем простой тип из полного: devices.types.light -> light
            device_type = self._extract_device_type(yandex_type)

            # Получаем capabilities (возможности устройства)
            yandex_capabilities = yandex_device.get("capabilities", [])
            capabilities = self._extract_capabilities(yandex_capabilities)

            # Получаем состояние устройства
            yandex_states = yandex_device.get("states", [])
            device_state = self._extract_state(yandex_states, capabilities)

            # Собираем в стандартный формат
            device = {
                "provider": "yandex",
                "external_id": device_id,
                "name": name,
                "type": device_type,
                "capabilities": capabilities,
                "state": device_state,
            }

            return device

        except Exception as e:
            # Ошибка преобразования одного устройства не блокирует остальные
            try:
                await self.runtime.service_registry.call(
                    "logger.log",
                    level="warning",
                    message=f"Ошибка преобразования устройства: {e}",
                    plugin=self.metadata.name,
                )
            except Exception:
                pass
            return None

    @staticmethod
    def _extract_device_type(yandex_type: str) -> str:
        """Извлечь простой тип из полного типа Яндекса.

        Примеры:
        - devices.types.light -> light
        - devices.types.smart_speaker -> smart_speaker
        - devices.types.thermostat -> thermostat

        Args:
            yandex_type: полный тип (devices.types.*)

        Returns:
            Простой тип устройства
        """
        if not yandex_type:
            return "unknown"

        # Извлекаем последнюю часть после последней точки
        parts = yandex_type.split(".")
        if parts:
            return parts[-1]
        return "unknown"

    @staticmethod
    def _extract_capabilities(yandex_capabilities: list) -> list[str]:
        """Извлечь список capabilities из ответа Яндекса.

        Структура capability:
        {
            "type": "devices.capabilities.on_off",
            "retrievable": true,
            "reportable": true,
            ...
        }

        Возвращает: ["on_off", "brightness", ...]

        Args:
            yandex_capabilities: список capabilities из ответа API

        Returns:
            Список простых имён capabilities
        """
        capabilities = []

        for cap in yandex_capabilities:
            cap_type = cap.get("type", "")
            if not cap_type:
                continue

            # Извлекаем простое имя: devices.capabilities.on_off -> on_off
            parts = cap_type.split(".")
            if parts:
                simple_name = parts[-1]
                capabilities.append(simple_name)

        return capabilities

    @staticmethod
    def _extract_state(yandex_states: list, capabilities: list[str]) -> Dict[str, Any]:
        """Извлечь состояние устройства из ответа Яндекса.

        Структура state:
        {
            "type": "devices.capabilities.on_off",
            "state": {
                "instance": "on",
                "value": true
            }
        }

        Возвращает состояние в формате: {"on": true, "brightness": 50, ...}

        Args:
            yandex_states: список states из ответа API
            capabilities: список capabilities для ориентира

        Returns:
            Словарь состояния
        """
        state = {}

        for state_item in yandex_states:
            cap_type = state_item.get("type", "")
            if not cap_type:
                continue

            # Извлекаем простое имя capability
            parts = cap_type.split(".")
            cap_name = parts[-1] if parts else ""

            # Получаем значение
            state_value = state_item.get("state", {})
            value = state_value.get("value")

            if value is not None:
                # Для capability on_off используем ключ "on", для остального используем cap_name
                if cap_name == "on_off":
                    state["on"] = value
                else:
                    state[cap_name] = value

        return state

    async def on_start(self) -> None:
        """Запуск: логируем инициализацию."""
        await super().on_start()

        try:
            await self.runtime.service_registry.call(
                "logger.log",
                level="info",
                message="yandex_smart_home_real_v0 запущен",
                plugin=self.metadata.name,
            )
        except Exception:
            pass

    async def on_stop(self) -> None:
        """Остановка: логируем завершение."""
        await super().on_stop()

        try:
            await self.runtime.service_registry.call(
                "logger.log",
                level="info",
                message="yandex_smart_home_real_v0 остановлен",
                plugin=self.metadata.name,
            )
        except Exception:
            pass

    async def on_unload(self) -> None:
        """Выгрузка: удаляем сервис."""
        await super().on_unload()

        try:
            self.runtime.service_registry.unregister("yandex.sync_devices")
        except Exception:
            pass
