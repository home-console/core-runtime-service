"""
Модуль для проверки онлайн статуса устройств через Яндекс API.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple
import asyncio
import time

from core.utils.operation import operation
from .api_client import YandexAPIClient


class DeviceStatusChecker:
    """Класс для проверки онлайн статуса устройств."""

    def __init__(self, runtime: Any, plugin_name: str):
        """Инициализация проверяющего статус.

        Args:
            runtime: экземпляр Runtime
            plugin_name: имя плагина для логирования
        """
        self.runtime = runtime
        self.plugin_name = plugin_name
        self.api_client = YandexAPIClient(runtime, plugin_name)

    async def check_devices_online(self) -> Dict[str, Any]:
        """Проверить онлайн статус всех устройств через Яндекс API.

        Запрашивает список устройств из API и обновляет online статус
        для каждого устройства на основе наличия в ответе API.

        Returns:
            Словарь с результатами проверки:
            {
                "checked": int,  # количество проверенных устройств
                "online": int,   # количество онлайн устройств
                "offline": int,  # количество оффлайн устройств
                "errors": list   # список ошибок
            }
        """
        async with operation("yandex.check_online", self.plugin_name, self.runtime):
            return await self._check_devices_online_impl()
    
    async def _check_devices_online_impl(self) -> Dict[str, Any]:
        """Реализация проверки онлайн статуса."""
        # Получаем список всех внутренних устройств с маппингами
        try:
            devices = await self.runtime.service_registry.call("devices.list")
            mappings = await self.runtime.service_registry.call("devices.list_mappings")
        except Exception as e:
            raise RuntimeError(f"Ошибка получения списка устройств: {e}")

        if not isinstance(devices, list) or not isinstance(mappings, list):
            raise RuntimeError("Некорректный формат данных устройств")

        # Создаём словарь маппингов: external_id -> internal_id
        external_to_internal = {}
        for mapping in mappings:
            if isinstance(mapping, dict):
                external_id = mapping.get("external_id")
                internal_id = mapping.get("internal_id")
                if external_id and internal_id:
                    external_to_internal[external_id] = internal_id

        # Проверяем онлайн-статус каждого устройства через отдельный запрос
        # Согласно документации: GET https://api.iot.yandex.net/v1.0/devices/{device_id}
        # Поле "state" в ответе содержит "online" или "offline"

        # Словарь для хранения статусов: external_id -> (online: bool, error: str | None)
        device_statuses: Dict[str, Tuple[bool, Optional[str]]] = {}
        errors = []

        # Функция для проверки одного устройства
        async def check_single_device(external_id: str) -> tuple[bool, Optional[str]]:
            """Проверяет онлайн-статус одного устройства."""
            try:
                device_info = await self.api_client.get_device_info(external_id)
                # Проверяем поле "state" в ответе
                state = device_info.get("state", "").lower()
                is_online = state == "online"

                # Логируем успешную проверку (debug уровень)
                try:
                    await self.runtime.service_registry.call(
                        "logger.log",
                        level="debug",
                        message=f"Device {external_id} status: {state}",
                        plugin=self.plugin_name,
                        context={"external_id": external_id, "state": state}
                    )
                except Exception:
                    pass

                return (is_online, None)
            except RuntimeError as e:
                error_msg = str(e)
                # Логируем ошибку
                try:
                    await self.runtime.service_registry.call(
                        "logger.log",
                        level="error",
                        message=f"Ошибка проверки устройства {external_id}: {error_msg}",
                        plugin=self.plugin_name,
                        context={"external_id": external_id}
                    )
                except Exception:
                    pass
                return (False, error_msg)
            except Exception as e:
                error_msg = f"Неожиданная ошибка для {external_id}: {e}"
                try:
                    await self.runtime.service_registry.call(
                        "logger.log",
                        level="error",
                        message=error_msg,
                        plugin=self.plugin_name,
                        context={"external_id": external_id, "error_type": type(e).__name__}
                    )
                except Exception:
                    pass
                return (False, error_msg)

        # Логируем начало проверки
        external_ids_to_check = list(external_to_internal.keys())
        try:
            await self.runtime.service_registry.call(
                "logger.log",
                level="info",
                message=f"Starting online status check for {len(external_ids_to_check)} devices",
                plugin=self.plugin_name,
                context={
                    "device_count": len(external_ids_to_check),
                    "external_ids": external_ids_to_check[:10]  # Первые 10 для примера
                }
            )
        except Exception:
            pass

        # Проверяем все устройства параллельно
        try:
            # Создаем задачи для параллельной проверки всех устройств
            tasks = []

            for external_id in external_ids_to_check:
                tasks.append(check_single_device(external_id))

            # Ждем результаты всех проверок
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Обрабатываем результаты
            for i, result in enumerate(results):
                external_id = external_ids_to_check[i]
                if isinstance(result, Exception):
                    error_msg = f"Исключение при проверке {external_id}: {result}"
                    device_statuses[external_id] = (False, error_msg)
                    errors.append(error_msg)
                else:
                    is_online, error = result
                    device_statuses[external_id] = (is_online, error)
                    if error:
                        errors.append(error)
        except Exception as e:
            error_msg = f"Критическая ошибка при проверке устройств: {e}"
            errors.append(error_msg)
            try:
                await self.runtime.service_registry.call(
                    "logger.log",
                    level="error",
                    message=error_msg,
                    plugin=self.plugin_name,
                    context={"error_type": type(e).__name__}
                )
            except Exception:
                pass

        # Обновляем статус для каждого устройства
        checked = 0
        online_count = 0
        offline_count = 0
        now = time.time()

        # Импортируем функцию для определения online статуса
        from modules.devices.services import _is_device_online

        for device in devices:
            if not isinstance(device, dict):
                continue

            device_id = device.get("id")
            if not device_id:
                continue

            # Находим external_id для этого устройства
            external_id = None
            for ext_id, int_id in external_to_internal.items():
                if int_id == device_id:
                    external_id = ext_id
                    break

            if not external_id:
                # Устройство не привязано к внешнему провайдеру - пропускаем
                continue

            checked += 1

            # Получаем статус устройства из результатов проверки
            if external_id in device_statuses:
                is_online, error = device_statuses[external_id]
            else:
                # Устройство не было проверено (не было в списке для проверки)
                is_online = False

            # Обновляем статус устройства
            try:
                device["last_seen"] = now if is_online else device.get("last_seen")
                device["online"] = _is_device_online(device["last_seen"]) if is_online else False
                device["updated_at"] = now

                await self.runtime.storage.set("devices", device_id, device)

                if is_online:
                    online_count += 1
                else:
                    offline_count += 1
            except Exception as e:
                errors.append(f"Ошибка обновления устройства {device_id}: {e}")

        # Логируем результаты проверки
        try:
            await self.runtime.service_registry.call(
                "logger.log",
                level="info",
                message=f"Online status check completed: {checked} checked, {online_count} online, {offline_count} offline",
                plugin=self.plugin_name,
                context={
                    "checked": checked,
                    "online": online_count,
                    "offline": offline_count,
                    "errors_count": len(errors)
                }
            )
        except Exception:
            pass

        return {
            "checked": checked,
            "online": online_count,
            "offline": offline_count,
            "errors": errors
        }
