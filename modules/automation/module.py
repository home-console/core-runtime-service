"""
AutomationModule — встроенный модуль автоматизации.

Обязательный домен системы, который регистрируется автоматически
при создании CoreRuntime через ModuleManager.
"""

from core.runtime_module import RuntimeModule
from . import handlers


class AutomationModule(RuntimeModule):
    """
    Модуль автоматизации.

    Подписывается на события external.device_state_reported и логирует
    изменения состояния устройств через service_registry.
    """

    @property
    def name(self) -> str:
        """Уникальное имя модуля."""
        return "automation"

    def register(self) -> None:
        """
        Регистрация модуля в CoreRuntime.

        Подписывается на событие external.device_state_reported.
        """
        # Подписываем обработчик события
        self.runtime.event_bus.subscribe(
            "external.device_state_reported",
            self._handle_external_state
        )

    async def start(self) -> None:
        """
        Запуск модуля.

        В текущей реализации automation не требует инициализации при старте,
        так как подписка на события происходит в register().
        """
        # Automation модуль не требует специальной инициализации при старте
        pass

    async def stop(self) -> None:
        """
        Остановка модуля.

        Отписывается от событий при остановке.
        """
        try:
            self.runtime.event_bus.unsubscribe(
                "external.device_state_reported",
                self._handle_external_state
            )
        except Exception:
            # Не ломаем остановку при ошибках отписки
            pass

    async def _handle_external_state(self, event_type: str, data: dict) -> None:
        """
        Обработчик события external.device_state_reported.

        Args:
            event_type: тип события
            data: payload события
        """
        await handlers.handle_external_state_reported(self.runtime, data)
