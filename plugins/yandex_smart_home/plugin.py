"""
Плагин `yandex_smart_home` — синхронизация реальных устройств Яндекса.

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

import asyncio

from core.base_plugin import BasePlugin, PluginMetadata
from .device_sync import DeviceSync
from .device_status import DeviceStatusChecker
from .command_handler import CommandHandler


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
            name="yandex_smart_home",
            version="0.1.0",
            description="Синхронизация реальных устройств из API Яндекса",
            author="Home Console",
        )

    async def on_load(self) -> None:
        """Загрузка: регистрируем сервисы."""
        await super().on_load()

        # Track background tasks started by this plugin so they can be
        # cancelled on unload to avoid leaked asyncio tasks.
        self._tasks: set = set()

        # Инициализируем модули
        self.device_sync = DeviceSync(self.runtime, self.metadata.name)
        self.device_status_checker = DeviceStatusChecker(self.runtime, self.metadata.name)
        self.command_handler = CommandHandler(self.runtime, self.metadata.name, self._tasks)

        # Регистрируем сервис синхронизации устройств
        async def _sync_devices():
            """Синхронизировать устройства из реального API Яндекса."""
            return await self.device_sync.sync_devices()

        await self.runtime.service_registry.register("yandex.sync_devices", _sync_devices)

        # Регистрируем сервис проверки онлайн статуса
        async def _check_devices_online():
            """Проверить онлайн статус всех устройств через Яндекс API."""
            return await self.device_status_checker.check_devices_online()

        await self.runtime.service_registry.register("yandex.check_devices_online", _check_devices_online)

        # HTTP endpoint регистрируется в AdminModule (admin.v1.yandex.sync)
        # для правильной обработки ошибок и формата ответа

    async def on_start(self) -> None:
        """Запуск: логируем инициализацию и подписываемся на события."""
        await super().on_start()

        try:
            await self.runtime.service_registry.call(
                "logger.log",
                level="info",
                message="yandex_smart_home запущен",
                plugin=self.metadata.name,
            )
        except Exception:
            pass

        # Подписаться на внутренние запросы команд от DevicesModule
        async def _internal_command_handler(event_type: str, data: dict):
            """Обработчик внутренних команд управления устройствами."""
            await self.command_handler.handle_command(data)

        # Сохранить хендлер и подписаться
        self._internal_command_handler = _internal_command_handler
        try:
            await self.runtime.event_bus.subscribe("internal.device_command_requested", self._internal_command_handler)
        except Exception:
            pass

    async def on_stop(self) -> None:
        """Остановка: логируем завершение."""
        await super().on_stop()

        try:
            await self.runtime.service_registry.call(
                "logger.log",
                level="info",
                message="yandex_smart_home остановлен",
                plugin=self.metadata.name,
            )
        except Exception:
            pass

    async def on_unload(self) -> None:
        """Выгрузка: удаляем сервисы и отменяем фоновые задачи."""
        await super().on_unload()

        # Cancel background tasks started by this plugin
        try:
            tasks = getattr(self, "_tasks", None)
            if tasks:
                # cancel
                for t in list(tasks):
                    try:
                        t.cancel()
                    except Exception:
                        pass

                # wait for completion with timeout
                try:
                    await asyncio.wait_for(asyncio.gather(*list(tasks), return_exceptions=True), timeout=2.0)
                except asyncio.TimeoutError:
                    # timed out waiting — tasks may still be running, but we've attempted cancel
                    pass
                except Exception:
                    # ignore other errors from tasks
                    pass

                # suppress CancelledError and clear tracking
                for t in list(tasks):
                    try:
                        if not t.done():
                            t.cancel()
                    except Exception:
                        pass
                try:
                    tasks.clear()
                except Exception:
                    pass

        except Exception:
            pass

        try:
            await self.runtime.service_registry.unregister("yandex.sync_devices")
        except Exception:
            pass

        try:
            await self.runtime.service_registry.unregister("yandex.check_devices_online")
        except Exception:
            pass
