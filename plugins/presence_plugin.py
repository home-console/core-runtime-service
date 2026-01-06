"""
Плагин `presence` — минимальный доменный плагин для отслеживания присутствия дома.

Модель состояния:
- ключ в runtime.state: "presence.home" (bool)

Сервисы:
- `presence.set(home: bool)` — установить состояние присутствия.

События:
- `presence.entered` (old_state, new_state) — False -> True
- `presence.left` (old_state, new_state) — True -> False

HTTP (декларативно):
- POST /presence/enter  -> service: presence.set(home=True)
- POST /presence/leave  -> service: presence.set(home=False)

Плагин взаимодействует только через runtime.state_engine, runtime.event_bus,
runtime.service_registry и runtime.http.
"""

from __future__ import annotations

from typing import Any, Optional

from core.http_registry import HttpEndpoint
from plugins.base_plugin import BasePlugin, PluginMetadata


class PresencePlugin(BasePlugin):
    """Доменный плагин `presence`.

    Простой, минимальный и без доменных деталей — только boolean ``presence.home``.
    """

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="presence",
            version="0.1.0",
            description="Минимальный плагин отслеживания присутствия дома",
            author="Home Console",
        )

    async def on_load(self) -> None:
        """Регистрация сервиса и HTTP-контрактов."""
        await super().on_load()
        # Сервис для управления присутствием
        async def _set_service(home: bool) -> Optional[bool]:
            """Сервис `presence.set`.

            Аргументы:
                home: bool — новое значение

            Возвращает новое значение состояния presence.home.
            """
            try:
                if not isinstance(home, bool):
                    raise ValueError("Аргумент 'home' должен быть типа bool")

                # Получаем старое состояние (может быть None)
                old = await self.runtime.state_engine.get("presence.home")
                old_val = bool(old) if isinstance(old, bool) else False

                # Если состояние не поменялось — ничего не делаем
                if old_val == home:
                    return old_val

                # Обновляем state
                await self.runtime.state_engine.set("presence.home", home)

                # Публикуем событие в зависимости от направления изменения
                payload = {"old_state": old_val, "new_state": home}
                if old_val is False and home is True:
                    await self.runtime.event_bus.publish("presence.entered", payload)
                elif old_val is True and home is False:
                    await self.runtime.event_bus.publish("presence.left", payload)

                return home

            except Exception as exc:  # логируем ошибки, но не ломаем Core
                try:
                    await self.runtime.service_registry.call(
                        "logger.log",
                        level="error",
                        message=f"presence.set error: {str(exc)}",
                        plugin=self.metadata.name,
                    )
                except Exception:
                    pass
                # Повторно выбрасываем, чтобы вызывающий получил информацию
                raise

        # Регистрируем сервис
        try:
            self.runtime.service_registry.register("presence.set", _set_service)
        except Exception:
            # Если регистрация не удалась — не ломаем загрузку
            pass

        # Регистрируем HTTP контракты декларативно
        try:
            # Указываем сервис с преднастроенным аргументом через query-like синтаксис,
            # чтобы адаптеры (HTTP/CLI) могли передать фиксированный параметр.
            self.runtime.http.register(HttpEndpoint(method="POST", path="/presence/enter", service="presence.set?home=true"))
            self.runtime.http.register(HttpEndpoint(method="POST", path="/presence/leave", service="presence.set?home=false"))
        except Exception:
            # Ошибки регистрации контрактов не должны блокировать загрузку
            pass

    async def on_start(self) -> None:
        """Инициализация состояния и логирование старта."""
        await super().on_start()
        try:
            cur = await self.runtime.state_engine.get("presence.home")
            if not isinstance(cur, bool):
                # Инициализируем в False, если отсутствует
                await self.runtime.state_engine.set("presence.home", False)
        except Exception:
            # Не мешаем старту системы, но логируем при возможности
            try:
                await self.runtime.service_registry.call(
                    "logger.log",
                    level="warning",
                    message="presence: failed to initialize state",
                    plugin=self.metadata.name,
                )
            except Exception:
                pass

        # Сообщаем, что плагин запущен
        try:
            await self.runtime.service_registry.call(
                "logger.log",
                level="info",
                message="Presence plugin started",
                plugin=self.metadata.name,
            )
        except Exception:
            pass

    async def on_stop(self) -> None:
        """Логирование остановки."""
        await super().on_stop()
        try:
            await self.runtime.service_registry.call(
                "logger.log",
                level="info",
                message="Presence plugin stopped",
                plugin=self.metadata.name,
            )
        except Exception:
            pass

    async def on_unload(self) -> None:
        """Выгрузка: удаление сервисов и контрактов, очистка ссылок."""
        await super().on_unload()
        try:
            # Удаляем сервис
            self.runtime.service_registry.unregister("presence.set")
        except Exception:
            pass

        try:
            # Удаляем HTTP контракты, принадлежащие плагину
            self.runtime.http.clear(self.metadata.name)
        except Exception:
            pass

        # Очистить ссылку на runtime
        self.runtime = None
