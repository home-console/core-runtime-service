"""
Модуль для трансформации устройств из формата Яндекс API в стандартный формат.

Преобразует устройства из ответа Яндекс API в формат, используемый в Home Console.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


class DeviceTransformer:
    """Класс для трансформации устройств Яндекс API."""

    @staticmethod
    def transform_device(yandex_device: Dict[str, Any]) -> Optional[Dict[str, Any]]:
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

        Структура выходного формата:
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
            name = yandex_device.get("name") or yandex_device.get("title") or device_id

            # Получаем тип устройства (формат: devices.types.light)
            yandex_type = yandex_device.get("type", "")

            # Извлекаем простой тип из полного: devices.types.light -> light
            device_type = DeviceTransformer._extract_device_type(yandex_type)

            # Получаем capabilities (возможности устройства)
            yandex_capabilities = yandex_device.get("capabilities", [])
            capabilities = DeviceTransformer._extract_capabilities(yandex_capabilities)

            # Получаем состояние устройства
            yandex_states = yandex_device.get("states", [])
            device_state = DeviceTransformer._extract_state(yandex_states, capabilities)

            # Извлекаем информацию о доме и комнате (если есть)
            home_id = yandex_device.get("house_id")
            home_name = yandex_device.get("house_name")
            room_id = yandex_device.get("room_id")
            room_name = yandex_device.get("room_name")
            
            # Если room_name не в корне, проверяем в parameters
            if not room_name:
                parameters = yandex_device.get("parameters", {})
                if isinstance(parameters, dict):
                    room_name = parameters.get("room_name")

            # Извлекаем онлайн статус
            device_state_value = yandex_device.get("state")
            online = device_state_value not in ("offline", None) if device_state_value else True

            # Собираем в стандартный формат
            device = {
                "provider": "yandex",
                "external_id": device_id,
                "name": name,
                "type": device_type,
                "capabilities": capabilities,
                "state": device_state,
            }

            # Добавляем информацию о доме/комнате, если есть
            if home_id:
                device["home_id"] = home_id
            if home_name:
                device["home_name"] = home_name
            if room_id:
                device["room_id"] = room_id
            if room_name:
                device["room_name"] = room_name
            if device_state_value is not None:
                device["online"] = online

            return device

        except Exception:
            # Ошибка преобразования одного устройства не блокирует остальные
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
                # Для capability on_off приводим значение к булеву типу (нормализуем 'on'/'off' и подобные)
                if cap_name == "on_off":
                    norm = None
                    if isinstance(value, bool):
                        norm = value
                    elif isinstance(value, str):
                        v = value.strip().lower()
                        if v in ("on", "true", "1", "yes"):
                            norm = True
                        elif v in ("off", "false", "0", "no"):
                            norm = False
                    elif isinstance(value, (int, float)):
                        norm = bool(value)

                    if norm is not None:
                        state["on"] = norm
                else:
                    state[cap_name] = value

        return state

    @staticmethod
    def convert_params_to_actions(params: Dict[str, Any]) -> list[Dict[str, Any]]:
        """Конвертировать параметры команды в действия Яндекс API.

        Args:
            params: параметры команды в формате {"on": true, "brightness": 50, ...}

        Returns:
            Список действий в формате Яндекс API
        """
        actions = []

        # Простая конверсия: if params has "on" -> devices.capabilities.on_off
        if "on" in params:
            actions.append({
                "type": "devices.capabilities.on_off",
                "state": {
                    "instance": "on",
                    "value": params["on"]
                }
            })

        # Если есть яркость -> brightness capability
        if "brightness" in params:
            actions.append({
                "type": "devices.capabilities.range",
                "state": {
                    "instance": "brightness",
                    "value": params["brightness"]
                }
            })

        # TODO: добавить другие capabilities (temperature, color_setting, etc.)

        return actions
