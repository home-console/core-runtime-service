"""
PresenceModule — встроенный модуль отслеживания присутствия.

Обязательный домен системы, который регистрируется автоматически
при создании CoreRuntime через ModuleManager.
"""

from typing import Optional

from core.runtime_module import RuntimeModule
from core.http_registry import HttpEndpoint


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
        # Регистрация сервиса
        await self.runtime.service_registry.register("presence.set", self._set_service)

        # Регистрация HTTP контрактов
        try:
            self.runtime.http.register(
                HttpEndpoint(
                    method="POST",
                    path="/presence/enter",
                    service="presence.set?home=true"
                )
            )
            self.runtime.http.register(
                HttpEndpoint(
                    method="POST",
                    path="/presence/leave",
                    service="presence.set?home=false"
                )
            )
        except Exception:
            # Ошибки регистрации контрактов не должны блокировать загрузку
            pass

    async def start(self) -> None:
        """
        Запуск модуля.

        Инициализирует состояние presence.home в False, если отсутствует.
        """
        try:
            cur = await self.runtime.storage.get("presence", "home")
            if not isinstance(cur, bool):
                # Инициализируем в False, если отсутствует
                await self.runtime.storage.set("presence", "home", False)
        except Exception:
            # Не мешаем старту системы
            pass

    async def stop(self) -> None:
        """
        Остановка модуля.

        Отменяет регистрацию сервиса и HTTP endpoints.
        """
        # Отмена регистрации сервиса
        try:
            await self.runtime.service_registry.unregister("presence.set")
        except Exception:
            pass

        # Удаление HTTP контрактов
        try:
            self.runtime.http.clear(self.name)
        except Exception:
            pass

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
            old = await self.runtime.storage.get("presence", "home")
            old_val = bool(old) if isinstance(old, bool) else False

            # Если состояние не поменялось — ничего не делаем
            if old_val == home:
                return old_val

            # Обновляем state через storage — storage является SOR
            await self.runtime.storage.set("presence", "home", home)

            # Публикуем событие в зависимости от направления изменения
            payload = {"old_state": old_val, "new_state": home}
            if old_val is False and home is True:
                await self.runtime.event_bus.publish("presence.entered", payload)
            elif old_val is True and home is False:
                await self.runtime.event_bus.publish("presence.left", payload)

            return home

        except Exception as exc:
            # Логируем ошибки, но не ломаем Core
            try:
                await self.runtime.service_registry.call(
                    "logger.log",
                    level="error",
                    message=f"presence.set error: {str(exc)}",
                    plugin="presence_module",
                )
            except Exception:
                pass
            # Повторно выбрасываем, чтобы вызывающий получил информацию
            raise
