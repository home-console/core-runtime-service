"""
Модуль для обработки команд управления устройствами через Яндекс API.
"""
from __future__ import annotations

from typing import Any, Dict
import asyncio

from .api_client import YandexAPIClient
from .device_transformer import DeviceTransformer


class CommandHandler:
    """Класс для обработки команд управления устройствами."""

    def __init__(self, runtime: Any, plugin_name: str, tasks: set):
        """Инициализация обработчика команд.

        Args:
            runtime: экземпляр Runtime
            plugin_name: имя плагина для логирования
            tasks: множество для отслеживания фоновых задач
        """
        self.runtime = runtime
        self.plugin_name = plugin_name
        self.tasks = tasks
        self.api_client = YandexAPIClient(runtime, plugin_name)

    async def handle_command(self, data: Dict[str, Any]) -> None:
        """Обработать команду управления устройством.

        Ожидаемый формат payload'а:
        {
            "internal_id": "...",
            "external_id": "...",
            "command": "set_state",
            "params": { ... }
        }

        Args:
            data: данные команды
        """
        try:
            await self.runtime.service_registry.call(
                "logger.log",
                level="debug",
                message=f"yandex_smart_home: received internal.device_command_requested",
                plugin=self.plugin_name,
                context={"data": data}
            )
        except Exception:
            pass

        external_id = data.get("external_id")
        params = data.get("params", {}) or {}

        # Если нет external_id, значит устройство не привязано к внешнему провайдеру
        # Проверяем, есть ли mapping для этого устройства в yandex
        if not external_id:
            internal_id = data.get("internal_id")
            if internal_id:
                # Проверяем, есть ли mapping для этого internal_id в yandex
                try:
                    mappings = await self.runtime.service_registry.call("devices.list_mappings")
                    if isinstance(mappings, list):
                        for mapping in mappings:
                            if isinstance(mapping, dict) and mapping.get("internal_id") == internal_id:
                                external_id = mapping.get("external_id")
                                break
                except Exception:
                    pass

        if not external_id:
            # Нечем управлять - сбрасываем pending
            try:
                await self.runtime.service_registry.call(
                    "logger.log",
                    level="warning",
                    message=f"internal.device_command_requested missing external_id: {data}",
                    plugin=self.plugin_name,
                )
            except Exception:
                pass
            # Сбрасываем pending при отсутствии external_id
            await self._reset_pending_on_error(data.get("internal_id"), None, "Missing external_id")
            return

        # Проверяем авторизацию
        try:
            status = await self.runtime.service_registry.call("oauth_yandex.get_status")
        except Exception:
            status = None

        if not status or not status.get("authorized"):
            try:
                await self.runtime.service_registry.call(
                    "logger.log",
                    level="warning",
                    message=f"Yandex not authorized, cannot send command for {external_id}",
                    plugin=self.plugin_name,
                )
            except Exception:
                pass
            # Сбрасываем pending при ошибке авторизации
            await self._reset_pending_on_error(data.get("internal_id"), external_id, "Yandex not authorized")
            return

        # Конвертируем params в действия по Яндекс API
        actions = DeviceTransformer.convert_params_to_actions(params)

        # Логируем исходящий запрос
        try:
            await self.runtime.service_registry.call(
                "logger.log",
                level="debug",
                message=f"Yandex command request",
                plugin=self.plugin_name,
                context={
                    "device_id": external_id,
                    "actions": actions,
                    "params": params,
                }
            )
        except Exception:
            pass

        try:
            # Отправляем команду
            await self.api_client.send_device_action(external_id, actions)

            # Успешный ответ — сразу публикуем оптимистичное обновление состояния
            # на основе отправленных параметров, затем запускаем polling для подтверждения
            try:
                # Оптимистично обновляем состояние сразу после успешной отправки команды
                if isinstance(params, dict) and "on" in params:
                    optimistic_reported = {
                        "external_id": external_id,
                        "state": {"on": params["on"]}
                    }
                    try:
                        # Публикуем событие и ждём его обработки
                        await self.runtime.event_bus.publish("external.device_state_reported", optimistic_reported)
                        await self.runtime.service_registry.call(
                            "logger.log",
                            level="info",
                            message=f"Optimistic state update published for {external_id}: on={params['on']}",
                            plugin=self.plugin_name,
                            context={
                                "internal_id": data.get("internal_id"),
                                "external_id": external_id,
                                "state": optimistic_reported["state"]
                            }
                        )
                    except Exception as pub_err:
                        await self.runtime.service_registry.call(
                            "logger.log",
                            level="error",
                            message=f"Failed to publish optimistic state update: {pub_err}",
                            plugin=self.plugin_name,
                            context={
                                "internal_id": data.get("internal_id"),
                                "external_id": external_id,
                                "error": str(pub_err)
                            }
                        )
                else:
                    # Логируем, если params не содержит "on"
                    try:
                        await self.runtime.service_registry.call(
                            "logger.log",
                            level="debug",
                            message=f"Optimistic update skipped: params does not contain 'on'",
                            plugin=self.plugin_name,
                            context={
                                "internal_id": data.get("internal_id"),
                                "external_id": external_id,
                                "params": params
                            }
                        )
                    except Exception:
                        pass
            except Exception as e:
                try:
                    await self.runtime.service_registry.call(
                        "logger.log",
                        level="error",
                        message=f"Exception in optimistic update logic: {e}",
                        plugin=self.plugin_name,
                        context={
                            "internal_id": data.get("internal_id"),
                            "external_id": external_id,
                            "error": str(e)
                        }
                    )
                except Exception:
                    pass

            # Также запускаем background polling для получения актуального
            # состояния устройства через GET /v1.0/devices (для подтверждения).
            try:
                # логируем факт успешной отправки команды
                try:
                    await self.runtime.service_registry.call(
                        "logger.log",
                        level="info",
                        message=f"Command sent successfully to Yandex device {external_id}",
                        plugin=self.plugin_name,
                        context={"state": params}
                    )
                except Exception:
                    pass

                # Запускаем фоновую задачу пуллинга (не ждём её)
                task = asyncio.create_task(
                    self._poll_and_publish(external_id, data.get("internal_id"), params)
                )
                # Track and auto-remove completed tasks
                try:
                    self.tasks.add(task)
                    task.add_done_callback(lambda t, tasks=self.tasks: tasks.discard(t))
                except Exception:
                    pass

            except Exception:
                pass

        except RuntimeError as e:
            # Ошибка от API — сбрасываем pending и логируем ошибку
            error_msg = str(e)
            try:
                await self.runtime.service_registry.call(
                    "logger.log",
                    level="error",
                    message=f"Yandex API error: {error_msg}",
                    plugin=self.plugin_name,
                    context={
                        "device_id": external_id,
                        "error": error_msg,
                    }
                )
            except Exception:
                pass

            # Сбрасываем pending при ошибке API
            await self._reset_pending_on_error(data.get("internal_id"), external_id, f"API error: {error_msg}")

        except Exception as e:
            # Прочие ошибки — сбрасываем pending
            try:
                await self.runtime.service_registry.call(
                    "logger.log",
                    level="error",
                    message=f"Error sending command to Yandex device {external_id}: {type(e).__name__}: {e}",
                    plugin=self.plugin_name,
                )
            except Exception:
                pass

            # Сбрасываем pending при прочих ошибках
            await self._reset_pending_on_error(data.get("internal_id"), external_id, f"Error: {type(e).__name__}")

    async def _poll_and_publish(self, external_id: str, internal_id: str | None, params: Dict[str, Any]) -> None:
        """Опрос устройства и публикация обновленного состояния.

        Args:
            external_id: внешний ID устройства
            internal_id: внутренний ID устройства
            params: параметры команды
        """
        # Уменьшаем задержку с 1.5 до 0.8 секунды для более быстрого обновления
        await asyncio.sleep(0.8)

        # Флаг для отслеживания успешного обновления состояния
        state_updated = False

        try:
            # Получаем список устройств из API
            devices_list_response = await self.api_client.get_devices_list()
            devices_list = devices_list_response.get("devices") or []

            # Найти устройство по external_id
            target = None
            for d in devices_list:
                if d.get("id") == external_id:
                    target = d
                    break

            if target is not None:
                # Извлечь состояние через существующий helper
                caps = DeviceTransformer._extract_capabilities(target.get("capabilities", []))
                state = DeviceTransformer._extract_state(target.get("states", []), caps)
                reported = {"external_id": external_id, "state": {}}
                if isinstance(state, dict) and "on" in state:
                    reported["state"]["on"] = state["on"]

                # Публикуем, только если нашли on/off
                if reported["state"]:
                    try:
                        await self.runtime.event_bus.publish("external.device_state_reported", reported)
                        state_updated = True
                    except Exception:
                        try:
                            await self.runtime.service_registry.call(
                                "logger.log",
                                level="warning",
                                message=f"Failed to publish external.device_state_reported after poll for {external_id}",
                                plugin=self.plugin_name,
                            )
                        except Exception:
                            pass
        except Exception:
            # Защищаем пуллинг от падений
            try:
                await self.runtime.service_registry.call(
                    "logger.log",
                    level="error",
                    message=f"Unexpected error in poll task for {external_id}",
                    plugin=self.plugin_name,
                )
            except Exception:
                pass

        # FALLBACK: Если состояние не было обновлено через polling, но команда была успешно отправлена,
        # оптимистично обновляем состояние на основе desired и сбрасываем pending
        if not state_updated:
            try:
                # Получаем device через internal_id для оптимистичного обновления
                device = await self.runtime.service_registry.call("devices.get", internal_id)
                if isinstance(device, dict):
                    device_state = device.get("state", {})
                    if isinstance(device_state, dict) and device_state.get("pending") is True:
                        # Оптимистично обновляем reported на основе desired
                        desired = device_state.get("desired", {})
                        if isinstance(desired, dict) and "on" in desired:
                            # Публикуем оптимистичное обновление состояния
                            optimistic_reported = {
                                "external_id": external_id,
                                "state": {"on": desired["on"]}
                            }
                            try:
                                await self.runtime.event_bus.publish("external.device_state_reported", optimistic_reported)
                                await self.runtime.service_registry.call(
                                    "logger.log",
                                    level="info",
                                    message=f"Optimistic state update for {external_id} (polling did not return device state)",
                                    plugin=self.plugin_name,
                                )
                            except Exception:
                                pass
            except Exception:
                # Игнорируем ошибки fallback, чтобы не ломать основной поток
                pass

    async def _reset_pending_on_error(
        self, internal_id: str | None, external_id: str | None, error_reason: str
    ) -> None:
        """Сбросить pending состояние устройства при ошибке отправки команды.

        Args:
            internal_id: внутренний ID устройства
            external_id: внешний ID устройства
            error_reason: причина ошибки для логирования
        """
        if not internal_id:
            try:
                await self.runtime.service_registry.call(
                    "logger.log",
                    level="debug",
                    message=f"_reset_pending_on_error: no internal_id provided",
                    plugin=self.plugin_name,
                )
            except Exception:
                pass
            return

        try:
            import time
            # Получаем текущее состояние устройства
            device = await self.runtime.service_registry.call("devices.get", internal_id)
            if not isinstance(device, dict):
                try:
                    await self.runtime.service_registry.call(
                        "logger.log",
                        level="debug",
                        message=f"_reset_pending_on_error: device {internal_id} not found or invalid",
                        plugin=self.plugin_name,
                    )
                except Exception:
                    pass
                return

            device_state = device.get("state", {})
            if not isinstance(device_state, dict) or device_state.get("pending") is not True:
                # Устройство уже не в pending состоянии
                try:
                    await self.runtime.service_registry.call(
                        "logger.log",
                        level="debug",
                        message=f"_reset_pending_on_error: device {internal_id} not in pending state",
                        plugin=self.plugin_name,
                        context={"pending": device_state.get("pending")}
                    )
                except Exception:
                    pass
                return

            # Сбрасываем pending, оставляя desired и reported без изменений
            # Это позволяет пользователю увидеть, что команда не была выполнена
            device_state["pending"] = False
            device["state"] = device_state
            device["updated_at"] = time.time()

            # Сохраняем обновленное состояние
            await self.runtime.storage.set("devices", internal_id, device)

            # Логируем сброс pending
            try:
                await self.runtime.service_registry.call(
                    "logger.log",
                    level="info",
                    message=f"Reset pending state for device {internal_id} ({external_id}): {error_reason}",
                    plugin=self.plugin_name,
                    context={
                        "desired": device_state.get("desired"),
                        "reported": device_state.get("reported")
                    }
                )
            except Exception:
                pass
        except Exception as e:
            # Логируем ошибку при сбросе pending
            try:
                await self.runtime.service_registry.call(
                    "logger.log",
                    level="error",
                    message=f"_reset_pending_on_error failed for {internal_id}: {e}",
                    plugin=self.plugin_name,
                )
            except Exception:
                pass
