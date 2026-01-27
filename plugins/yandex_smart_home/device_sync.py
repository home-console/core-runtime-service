"""
Модуль для синхронизации устройств из Яндекс API.

Обеспечивает получение устройств из API и публикацию событий об их обнаружении.
"""
from __future__ import annotations

from typing import Any, Dict, List

from core.utils.operation import operation
from .api_client import YandexAPIClient
from .device_transformer import DeviceTransformer


class DeviceSync:
    """Класс для синхронизации устройств."""

    def __init__(self, runtime: Any, plugin_name: str):
        """Инициализация синхронизатора.

        Args:
            runtime: экземпляр Runtime
            plugin_name: имя плагина для логирования
        """
        self.runtime = runtime
        self.plugin_name = plugin_name
        self.api_client = YandexAPIClient(runtime, plugin_name)

    async def sync_devices(self) -> List[Dict[str, Any]]:
        """Синхронизировать устройства из реального API Яндекса.

        Этапы:
        1. Проверить feature flag `yandex.use_real_api`
        2. Получить токены из oauth_yandex.get_tokens()
        3. Выполнить HTTP GET к https://api.iot.yandex.net/v1.0/user/info
        4. Преобразовать каждое устройство в стандартный формат
        5. Опубликовать external.device_discovered для каждого
        6. Вернуть список преобразованных устройств

        Returns:
            Список устройств в стандартном формате

        Raises:
            RuntimeError: если токены недоступны или запрос к API не удался
        """
        async with operation("yandex.sync_devices", self.plugin_name, self.runtime):
            return await self._sync_devices_impl()
    
    async def _sync_devices_impl(self) -> List[Dict[str, Any]]:
        """Реализация синхронизации устройств."""
        # Feature flag: check storage key `yandex.use_real_api`
        try:
            use_real_data = await self.runtime.storage.get("yandex", "use_real_api")
            # Storage returns dict, check if it's truthy or has "enabled" key
            if isinstance(use_real_data, dict):
                use_real = use_real_data.get("enabled", False) if use_real_data else False
            else:
                use_real = bool(use_real_data)
        except Exception:
            use_real = False

        if not use_real:
            # Not enabled — signal to caller that real API is disabled
            raise RuntimeError("use_real_api_disabled")

        # Пытаемся получить устройства через Quasar API (с домами/комнатами)
        # Если не получается, fallback на OAuth API
        yandex_devices = []
        households = []
        
        try:
            # Пробуем Quasar API (требует cookies)
            quasar_response = await self.api_client.get_quasar_devices()
            
            # Структура Quasar API: {"status": "ok", "households": [...]}
            if isinstance(quasar_response, dict) and quasar_response.get("status") == "ok":
                households = quasar_response.get("households", [])
                
                # Извлекаем все устройства из всех домов
                for house in households:
                    house_id = house.get("id")
                    house_name = house.get("name")
                    all_devices = house.get("all", [])
                    
                    # Добавляем информацию о доме к каждому устройству
                    for device in all_devices:
                        device["house_id"] = house_id
                        device["house_name"] = house_name
                        yandex_devices.append(device)
                
                # Логируем успех
                try:
                    await self.runtime.service_registry.call(
                        "logger.log",
                        level="info",
                        message=f"Loaded {len(yandex_devices)} devices from Quasar API ({len(households)} households)",
                        plugin=self.plugin_name,
                    )
                except Exception:
                    pass
        except Exception as e:
            # Quasar API не доступен (нет cookies или ошибка) - fallback на OAuth API
            try:
                await self.runtime.service_registry.call(
                    "logger.log",
                    level="warning",
                    message=f"Quasar API unavailable, falling back to OAuth API: {e}",
                    plugin=self.plugin_name,
                )
            except Exception:
                pass
            
            # Fallback: используем OAuth API
            api_response = await self.api_client.get_user_info()
            
            # Структура ответа OAuth API: {"devices": [...]}
            if isinstance(api_response, dict) and "devices" in api_response:
                yandex_devices = api_response.get("devices", [])
            elif isinstance(api_response, list):
                yandex_devices = api_response

        # ЭТАП 3-4: Преобразовать устройства и опубликовать события
        devices = []

        for yandex_device in yandex_devices:
            # Преобразуем устройство в стандартный формат
            device = DeviceTransformer.transform_device(yandex_device)

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
                            plugin=self.plugin_name,
                        )
                    except Exception:
                        pass

        return devices
