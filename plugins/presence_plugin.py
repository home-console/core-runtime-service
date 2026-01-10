"""
DEPRECATED: Этот плагин заменён модулем modules.presence.PresenceModule.

Оставлен для обратной совместимости.
Будет удалён в версии 1.0.0.

Вся доменная логика presence теперь в modules/presence/module.py.
PresenceModule регистрируется автоматически при создании CoreRuntime
через ModuleManager.

Этот плагин больше не нужен и может быть удалён.
"""

from __future__ import annotations

from typing import Optional

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
        """
        DEPRECATED: Presence теперь регистрируется автоматически через ModuleManager.

        Этот метод больше не выполняет никаких действий.
        Модуль presence регистрируется при создании CoreRuntime.
        """
        await super().on_load()
        # PresenceModule уже зарегистрирован через ModuleManager
        # Ничего делать не нужно
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

                # Получаем старое состояние (может быть None) — читаем из storage
                old = await self.runtime.storage.get("presence", "home")
                # Извлекаем значение из dict, если это dict, иначе считаем False
                if isinstance(old, dict):
                    old_val = old.get("value", False)
                    if not isinstance(old_val, bool):
                        old_val = False
                else:
                    old_val = False

                # Если состояние не поменялось — ничего не делаем
                if old_val == home:
                    return old_val

                # Обновляем state через storage — storage является SOR
                # Storage требует dict, поэтому оборачиваем bool в dict
                await self.runtime.storage.set("presence", "home", {"value": home})

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
            await self.runtime.service_registry.register("presence.set", _set_service)
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
            cur = await self.runtime.storage.get("presence", "home")
            if cur is None or not isinstance(cur, dict) or cur.get("value") is None:
                # Инициализируем в False, если отсутствует
                await self.runtime.storage.set("presence", "home", {"value": False})
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
            await self.runtime.service_registry.unregister("presence.set")
        except Exception:
            pass

        try:
            # Удаляем HTTP контракты, принадлежащие плагину
            self.runtime.http.clear(self.metadata.name)
        except Exception:
            pass

        # Очистить ссылку на runtime
        self.runtime = None
