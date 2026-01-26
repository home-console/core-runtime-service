"""
Плагин `yandex_smart_home` — синхронизация реальных устройств Яндекса.

Назначение:
- получить устройства из реального API Яндекса
- преобразовать их в стандартный формат
- опубликовать события об обнаружении устройств
- realtime обновления через Quasar WebSocket

Архитектура:
- plugin-first, in-process
- использует ДВА разных API Яндекса:
  
  1) OAuth API (api.iot.yandex.net):
     - Официальный публичный API
     - Авторизация: OAuth Bearer token
     - Используется для: команды, initial sync
     - Токены через oauth_yandex.get_tokens()
  
  2) Quasar API (iot.quasar.yandex.ru):
     ⚠️ КРИТИЧНО: НЕ использует OAuth!
     - Внутренний reverse-engineered API
     - Авторизация: cookies сессии (Session_id, yandexuid)
     - Используется для: realtime WebSocket обновления
     - Cookies через oauth_yandex.get_cookies()

См. QUASAR_ARCHITECTURE_RULE.md для деталей.

Публикует события:
- external.device_discovered для каждого полученного устройства
- external.device_state_reported для realtime обновлений

Ограничения:
- НЕ интегрирует Алису
- НЕ делает refresh token (это задача oauth_yandex)

Комментарии на русском языке.
"""
from __future__ import annotations

import asyncio

from core.base_plugin import BasePlugin, PluginMetadata
from .device_sync import DeviceSync
from .device_status import DeviceStatusChecker
from .command_handler import CommandHandler
from .yandex_quasar_ws import YandexQuasarWS


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
        self.quasar_ws = YandexQuasarWS(self.runtime, self.metadata.name)
        # Передаем quasar_ws в command_handler для проверки активности WebSocket
        self.command_handler = CommandHandler(self.runtime, self.metadata.name, self._tasks, self.quasar_ws)

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

        async def _subscribe_device_updates(device_id: str, callback):
            """Подписка на обновления состояния конкретного устройства (ws)."""
            return self.quasar_ws.subscribe(device_id, callback)

        await self.runtime.service_registry.register("yandex.subscribe_device_updates", _subscribe_device_updates)

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

        # Подписываемся на событие успешной device-авторизации
        async def _on_device_auth_linked(event_type: str, data: dict):
            """Обработчик события yandex.device_auth.linked."""
            try:
                if data.get("quasar_ready"):
                    await self.runtime.service_registry.call(
                        "logger.log",
                        level="info",
                        message="Device auth linked, starting Quasar WS",
                        plugin=self.metadata.name,
                    )
                    await self.quasar_ws.start()
                    runner = self.quasar_ws.runner
                    if runner:
                        self._tasks.add(runner)
                        runner.add_done_callback(lambda t, tasks=self._tasks: tasks.discard(t))
            except Exception as e:
                await self.runtime.service_registry.call(
                    "logger.log",
                    level="error",
                    message=f"Failed to start Quasar WS after device auth: {e}",
                    plugin=self.metadata.name,
                )

        self._device_auth_handler = _on_device_auth_linked
        try:
            await self.runtime.event_bus.subscribe("yandex.device_auth.linked", self._device_auth_handler)
        except Exception:
            pass

        # Запустить realtime-поток Quasar, если включён реальный API и есть cookies
        try:
            if await self._is_real_api_enabled():
                # Проверяем наличие cookies (либо из device_auth, либо из oauth)
                cookies = await self._get_cookies()
                if cookies:
                    await self.quasar_ws.start()
                    runner = self.quasar_ws.runner
                    if runner:
                        self._tasks.add(runner)
                        runner.add_done_callback(lambda t, tasks=self._tasks: tasks.discard(t))
                else:
                    await self.runtime.service_registry.call(
                        "logger.log",
                        level="warning",
                        message="Quasar WS not started: cookies not found. Use device auth or OAuth with cookies.",
                        plugin=self.metadata.name,
                    )
        except Exception:
            pass

    async def _get_cookies(self):
        """Получить cookies с приоритетом: device_auth → oauth_yandex."""
        # 1. Проверяем device_auth
        try:
            session = await self.runtime.storage.get("yandex", "device_auth/session")
            if session and isinstance(session, dict) and session.get("cookies"):
                return session["cookies"]
        except Exception:
            pass
        
        # 2. Fallback на oauth_yandex
        try:
            if await self.runtime.service_registry.has_service("oauth_yandex.get_cookies"):
                cookies = await self.runtime.service_registry.call("oauth_yandex.get_cookies")
                if cookies:
                    return cookies
        except Exception:
            pass
        
        # 3. Fallback на прямой storage (старая схема)
        try:
            cookies = await self.runtime.storage.get("yandex", "cookies")
            if isinstance(cookies, dict):
                return cookies
        except Exception:
            pass
        
        return None

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

        try:
            await self.quasar_ws.stop()
        except Exception:
            pass

    async def on_unload(self) -> None:
        """Выгрузка: удаляем сервисы и отменяем фоновые задачи."""
        await super().on_unload()

        # Отписываемся от событий
        try:
            if hasattr(self, '_device_auth_handler'):
                await self.runtime.event_bus.unsubscribe("yandex.device_auth.linked", self._device_auth_handler)
        except Exception:
            pass

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

        try:
            await self.runtime.service_registry.unregister("yandex.subscribe_device_updates")
        except Exception:
            pass

        try:
            await self.quasar_ws.stop()
        except Exception:
            pass

    async def _is_real_api_enabled(self) -> bool:
        """Проверка feature-флага использования реального API."""
        try:
            use_real_data = await self.runtime.storage.get("yandex", "use_real_api")
            if isinstance(use_real_data, dict):
                return bool(use_real_data.get("enabled", False))
            return bool(use_real_data)
        except Exception:
            return False
