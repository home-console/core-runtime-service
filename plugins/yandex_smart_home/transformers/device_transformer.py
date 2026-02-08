"""
Модуль для трансформации устройств из формата Яндекс API в стандартный формат.

Преобразует устройства из ответа Яндекса в формат, используемый в Home Console.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


class DeviceTransformer:
    """Класс для трансформации устройств Яндекс API."""

    @staticmethod
    def transform_device(yandex_device: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            device_id = yandex_device.get("id")
            if not device_id:
                return None

            name = yandex_device.get("name") or yandex_device.get("title") or device_id
            yandex_type = yandex_device.get("type", "")
            device_type = DeviceTransformer._extract_device_type(yandex_type)

            yandex_capabilities = yandex_device.get("capabilities", [])
            capabilities = DeviceTransformer._extract_capabilities(yandex_capabilities)

            yandex_states = yandex_device.get("states", [])
            device_state = DeviceTransformer._extract_state(yandex_states, capabilities)

            home_id = yandex_device.get("house_id")
            home_name = yandex_device.get("house_name")
            room_id = yandex_device.get("room_id")
            room_name = yandex_device.get("room_name")
            if not room_name:
                parameters = yandex_device.get("parameters", {})
                if isinstance(parameters, dict):
                    room_name = parameters.get("room_name")

            device_state_value = yandex_device.get("state")
            online = device_state_value not in ("offline", None) if device_state_value else True

            device = {
                "provider": "yandex",
                "external_id": device_id,
                "name": name,
                "type": device_type,
                "capabilities": capabilities,
                "state": device_state,
            }

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
            return None

    @staticmethod
    def _extract_device_type(yandex_type: str) -> str:
        if not yandex_type:
            return "unknown"
        parts = yandex_type.split(".")
        if parts:
            return parts[-1]
        return "unknown"

    @staticmethod
    def _extract_capabilities(yandex_capabilities: list) -> list[str]:
        capabilities = []
        for cap in yandex_capabilities:
            cap_type = cap.get("type", "")
            if not cap_type:
                continue
            parts = cap_type.split(".")
            if parts:
                simple_name = parts[-1]
                capabilities.append(simple_name)
        return capabilities

    @staticmethod
    def _extract_state(yandex_states: list, capabilities: list[str]) -> Dict[str, Any]:
        state = {}
        for state_item in yandex_states:
            cap_type = state_item.get("type", "")
            if not cap_type:
                continue
            parts = cap_type.split(".")
            cap_name = parts[-1] if parts else ""
            state_value = state_item.get("state", {})
            value = state_value.get("value")
            if value is not None:
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
        actions = []
        if "on" in params:
            actions.append({
                "type": "devices.capabilities.on_off",
                "state": {"instance": "on", "value": params["on"]}
            })
        if "brightness" in params:
            actions.append({
                "type": "devices.capabilities.range",
                "state": {"instance": "brightness", "value": params["brightness"]}
            })
        return actions

    @staticmethod
    def convert_params_to_quasar_states(params: Dict[str, Any]) -> list[Dict[str, Any]]:
        """Формат для Quasar API: state только с value (без instance), часть клиентов так ожидает."""
        states = []
        if "on" in params:
            states.append({
                "type": "devices.capabilities.on_off",
                "state": {"value": bool(params["on"])}
            })
        if "brightness" in params:
            states.append({
                "type": "devices.capabilities.range",
                "state": {"instance": "brightness", "value": params["brightness"]}
            })
        return states
