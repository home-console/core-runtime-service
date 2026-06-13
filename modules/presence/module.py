"""
PresenceModule — встроенный модуль отслеживания присутствия.

Обязательный домен системы, который регистрируется автоматически
при создании CoreRuntime через ModuleManager.
"""

from typing import Optional

from core.runtime.runtime_module import RuntimeModule
from core.http.models import HttpEndpoint, EndpointAuthConfig
from modules.api.schemas import OkResponse
from core.events_schemas import PresenceEnteredPayload, PresenceLeftPayload
import logging
logger = logging.getLogger(__name__)


class PresenceModule(RuntimeModule):
    """
    Модуль отслеживания присутствия дома.

    Управляет состоянием presence.home (bool) и публикует события
    presence.entered и presence.left при изменении состояния.
    """

    @property
    def name(self) -> str:
        """Уникальное имя модуля."""
        return "presence"

    async def register(self) -> None:
        """
        Регистрация модуля в CoreRuntime.

        Регистрирует сервис presence.set и HTTP endpoints.
        """
        # Регистрация сервисов
        await self.context.services.register("presence.set", self._set_service)

        # Публичные HTTP ручки должны быть декларативны.
        # Превращаем legacy "presence.set?home=true" в явные сервисы.
        async def _enter(**kw):
            await self._set_service(True)
            return {"ok": True}

        async def _leave(**kw):
            await self._set_service(False)
            return {"ok": True}

        await self.context.services.register("presence.enter", _enter)
        await self.context.services.register("presence.leave", _leave)

        # Регистрация HTTP контрактов
        try:
            _presence_write = EndpointAuthConfig(required_scopes=["presence.write"])
            self.context.http.register(
                HttpEndpoint(
                    method="POST",
                    path="/api/v1/presence/enter",
                    service="presence.enter",
                    auth_config=_presence_write,
                    tags=["Presence"],
                    response_model=OkResponse,
                )
            )
            self.context.http.register(
                HttpEndpoint(
                    method="POST",
                    path="/api/v1/presence/leave",
                    service="presence.leave",
                    auth_config=_presence_write,
                    tags=["Presence"],
                    response_model=OkResponse,
                )
            )
        except Exception:
            # Ошибки регистрации контрактов не должны блокировать загрузку
            logger.debug("module.register: unexpected error (suppressed)", exc_info=True)
            pass

    async def start(self) -> None:
        """
        Запуск модуля.

        Инициализирует состояние presence.home в False, если отсутствует.
        """
        try:
            cur = await self.context.storage.get("presence", "home")
            if cur is None or not isinstance(cur, dict) or cur.get("value") is None:
                # Инициализируем в False, если отсутствует
                await self.context.storage.set("presence", "home", {"value": False})
        except Exception:
            # Не мешаем старту системы
            logger.debug("module.start: unexpected error (suppressed)", exc_info=True)
            pass

    async def stop(self) -> None:
        """
        Остановка модуля.

        Отменяет регистрацию сервиса и HTTP endpoints.
        """
        # Отмена регистрации сервиса
        try:
            await self.context.services.unregister("presence.set")
            await self.context.services.unregister("presence.enter")
            await self.context.services.unregister("presence.leave")
        except Exception:
            logger.warning("Unhandled exception", exc_info=True)

        # Удаление HTTP контрактов
        try:
            self.context.http.clear(self.name)
        except Exception:
            logger.warning("Unhandled exception", exc_info=True)

    async def _set_service(self, home: bool) -> Optional[bool]:
        """
        Сервис `presence.set`.

        Args:
            home: bool — новое значение

        Returns:
            новое значение состояния presence.home
        """
        try:
            if not isinstance(home, bool):
                raise ValueError("Аргумент 'home' должен быть типа bool")

            # Получаем старое состояние (может быть None) — читаем из storage
            old = await self.context.storage.get("presence", "home")
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
            await self.context.storage.set("presence", "home", {"value": home})

            # Публикуем событие в зависимости от направления изменения
            payload: PresenceEnteredPayload | PresenceLeftPayload = {
                "old_state": old_val,
                "new_state": home,
            }
            if old_val is False and home is True:
                await self.context.event_bus.publish("presence.entered", payload)
            elif old_val is True and home is False:
                await self.context.event_bus.publish("presence.left", payload)

            return home

        except Exception as exc:
            # Логируем ошибки, но не ломаем Core
            try:
                await self.context.services.call(
                    "logger.log",
                    level="error",
                    message=f"presence.set error: {str(exc)}",
                    plugin="presence_module",
                )
            except Exception:
                logger.warning("Unhandled exception", exc_info=True)
            # Повторно выбрасываем, чтобы вызывающий получил информацию
            raise
