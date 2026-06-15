"""
DevicesModule — встроенный модуль управления устройствами.

Обязательный домен системы, который регистрируется автоматически
при создании CoreRuntime через ModuleManager.
"""

import asyncio
import logging
import os
import time
from typing import Any, Optional

from core.runtime.runtime_module import RuntimeModule

from . import handlers, services

logger = logging.getLogger(__name__)


class DevicesModule(RuntimeModule):
    """
    Модуль управления устройствами.

    Регистрирует сервисы для работы с устройствами и подписывается
    на события внешних устройств.
    """

    def __init__(self, runtime: Any):
        super().__init__(runtime)
        # Used to warn when external.* publishers are not producing events.
        self._external_state_received_at: Optional[float] = None
        self._external_discovered_received_at: Optional[float] = None
        self._external_publish_watchdog_task: Optional[asyncio.Task[None]] = None
        self._external_publish_watchdog_stop: Optional[asyncio.Event] = None

    @property
    def name(self) -> str:
        """Уникальное имя модуля."""
        return "devices"

    async def register(self) -> None:
        """
        Регистрация модуля в CoreRuntime.

        Регистрирует сервисы devices.* и подписывается на события.
        HttpEndpoint не регистрируются — devices доступны только через operations.
        """
        # Регистрация сервисов (+ централизованный ACL через ServiceRegistry.register_with_acl)
        service_names = [
            ("devices.list", services.list_devices),
            ("devices.get", services.get_device),
            ("devices.create", services.create_device),
            ("devices.set_state", services.set_state),
            ("devices.list_external", services.list_external),
            ("devices.create_mapping", services.create_mapping),
            ("devices.list_mappings", services.list_mappings),
            ("devices.get_external_for_device", services.get_external_for_device),
            ("devices.delete_mapping", services.delete_mapping),
            ("devices.auto_map_external", services.auto_map_external),
            ("devices.auto_map_own", services.auto_map_own),
            ("devices.get_hung_pending", services.get_hung_pending_devices),
            ("devices.clear_pending", services.clear_pending_device),
            ("devices.update_device_fields", services.update_device_fields),
        ]

        acl_meta = {
            "devices.list": {"resource": "device", "filter_result": True},
            "devices.get": {"resource": "device", "enforce_result": True},
            # на create делаем owner injection (owner_id=ctx.user_id), без копипасты в services.py
            "devices.create": {"inject_owner_param": "owner_id"},
            # для set_state делаем preload устройства до выполнения (важно: write)
            "devices.set_state": {"resource": "device", "preload": "device_by_id"},
            # для update_device_fields делаем preload (для ACL проверки)
            "devices.update_device_fields": {
                "resource": "device",
                "preload": "device_by_id",
            },
            # инвентарь/маппинги — admin-only при наличии ctx
            "devices.list_external": {"admin_only": True},
            "devices.create_mapping": {"admin_only": True},
            "devices.list_mappings": {"admin_only": True},
            # get_external_for_device — доступен при devices.read (Product API проверяет доступ через devices.get)
            "devices.get_external_for_device": {
                "resource": "device",
                "preload": "device_by_id",
            },
            "devices.delete_mapping": {"admin_only": True},
            "devices.auto_map_external": {"admin_only": True},
            # auto_map_own — НЕ admin_only: self-service для интеграционных плагинов
            # (доступ ограничивается через allowed_services в манифесте плагина,
            # provider обязателен — плагин может смаппить только свои устройства).
            "devices.auto_map_own": {},
            # Diagnostics — admin-only
            "devices.get_hung_pending": {"admin_only": True},
            "devices.clear_pending": {"admin_only": True},
        }

        self._registered_services = []

        for name, func in service_names:
            # Skip services that are already registered (idempotent)
            try:
                if await self.context.services.has_service(name):
                    continue
            except Exception:
                # If service_registry doesn't implement has_service for some reason,
                # fall back to attempting registration and catching ValueError below.
                logger.debug("module.register: unexpected error (suppressed)", exc_info=True)
                pass

            try:
                meta = acl_meta.get(name, {})

                # preload loaders
                preload_resource = None
                if meta.get("preload") == "device_by_id":
                    storage = (
                        self.context.storage
                        if hasattr(self, "context") and self.context
                        else self.context.storage
                    )

                    async def _preload(args, kwargs, _storage=storage):
                        device_id = None
                        if args:
                            device_id = args[0]
                        if device_id is None:
                            device_id = kwargs.get("device_id") or kwargs.get("id")
                        if not device_id:
                            return None
                        return await _storage.get("devices", device_id)

                    preload_resource = _preload

                await self.register_runtime_service(
                    name,
                    func,
                    resource=meta.get("resource"),
                    admin_only=bool(meta.get("admin_only", False)),
                    filter_result=bool(meta.get("filter_result", False)),
                    enforce_result=bool(meta.get("enforce_result", False)),
                    preload_resource=preload_resource,
                    inject_owner_param=meta.get("inject_owner_param"),
                )
                self._registered_services.append(name)
            except ValueError:
                # already registered concurrently — skip
                continue

        # Подписка на события
        await self.context.event_bus.subscribe(
            "external.device_state_reported", self._handle_external_state
        )
        await self.context.event_bus.subscribe(
            "external.device_discovered", self._handle_external_device_discovered
        )

    async def start(self) -> None:
        """
        Запуск модуля.

        Регистрирует операции devices (device.set_state, device.mapping.*)
        и запускает background cleaner для зависших pending команд.
        """
        from .operations import register_device_operations

        register_device_operations(self.runtime)

        # Запускаем background cleaner для зависших pending команд
        try:
            from .pending_cleaner import start_pending_cleaner

            await start_pending_cleaner(self.runtime)
        except Exception as e:
            # Логируем но не ломаем старт модуля
            try:
                await self.context.services.call(
                    "logger.log",
                    level="warning",
                    message=f"Failed to start pending cleaner: {e}",
                    module="devices",
                )
            except Exception:
                logger.warning("Unhandled exception", exc_info=True)

        # Watchdog: if no external.* events appear shortly after startup,
        # it likely means publisher plugins are not loaded or not producing data.
        try:
            self._external_publish_watchdog_stop = asyncio.Event()
            self._external_publish_watchdog_task = asyncio.create_task(
                self._external_publish_watchdog()
            )
        except Exception:
            # Never block startup on watchdog issues.
            logger.debug("module.start: unexpected error (suppressed)", exc_info=True)
            pass

    async def _external_publish_watchdog(self) -> None:
        delay_s = float(
            os.getenv("EXTERNAL_EVENTS_PUBLISHER_WARN_DELAY_SECONDS", "5.0")
        )
        if delay_s <= 0:
            return
        stop_event = self._external_publish_watchdog_stop
        if stop_event is None:
            return

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=delay_s)
            return  # stopped
        except asyncio.CancelledError:
            return  # task cancelled during runtime/module shutdown
        except asyncio.TimeoutError:
            pass  # no events seen during delay window

        if self._external_state_received_at is None:
            logger.warning(
                "No publications for external.device_state_reported observed for %.1fs after startup. "
                "Check that publisher plugins are loaded and producing events.",
                delay_s,
            )

        if self._external_discovered_received_at is None:
            logger.warning(
                "No publications for external.device_discovered observed for %.1fs after startup. "
                "Check that publisher plugins are loaded and producing events.",
                delay_s,
            )

    async def stop(self) -> None:
        """
        Остановка модуля.

        Отписывается от событий и отменяет регистрацию сервисов.
        """
        # Отписка от событий
        try:
            await self.context.event_bus.unsubscribe(
                "external.device_state_reported", self._handle_external_state
            )
        except Exception:
            logger.warning("Unhandled exception", exc_info=True)

        try:
            await self.context.event_bus.unsubscribe(
                "external.device_discovered", self._handle_external_device_discovered
            )
        except Exception:
            logger.warning("Unhandled exception", exc_info=True)

        # Stop watchdog task (prevents "Task destroyed while pending" in tests).
        if self._external_publish_watchdog_stop is not None:
            self._external_publish_watchdog_stop.set()
        if self._external_publish_watchdog_task is not None:
            self._external_publish_watchdog_task.cancel()
            try:
                await self._external_publish_watchdog_task
            except asyncio.CancelledError:
                pass

        # Отмена регистрации сервисов
        for service_name in getattr(self, "_registered_services", []):
            try:
                await self.context.services.unregister(service_name)
            except Exception:
                logger.warning("Unhandled exception", exc_info=True)

    async def _handle_external_state(self, event_type: str, data: dict) -> None:
        """Обработчик события external.device_state_reported."""
        self._external_state_received_at = time.time()
        await handlers.handle_external_state(self.runtime, data)

    async def _handle_external_device_discovered(
        self, event_type: str, data: dict
    ) -> None:
        """Обработчик события external.device_discovered."""
        self._external_discovered_received_at = time.time()
        await handlers.handle_external_device_discovered(self.runtime, data)
