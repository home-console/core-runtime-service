"""
AutomationModule — встроенный модуль автоматизации.

Доменный оркестратор (Automation / Flows), который подключается на уровне приложения
через bootstrap и может быть отключён/удалён без влияния на Core.
"""

from core.runtime_module import RuntimeModule

from . import handlers
from .events import device_state_to_operation
from .registry import get_event_handlers, register_event_handler
from .operations import handle_automation_run


class AutomationModule(RuntimeModule):
    """
    Модуль автоматизации.

    Контракт:
    - automation не является частью Core
    - automation не вызывает доменные сервисы напрямую
    - automation использует ТОЛЬКО EventBus + Operations (+ storage/state при необходимости)
    - automation не знает, где/как исполняются операции
    """

    @property
    def name(self) -> str:
        """Уникальное имя модуля."""
        return "automation"

    async def register(self) -> None:
        """
        Регистрация модуля в CoreRuntime.

        Подписывается на событие external.device_state_reported.
        Дальше — только оркестрация через создание operations.
        """
        handlers = get_event_handlers("external.device_state_reported")
        if device_state_to_operation not in handlers:
            register_event_handler(
                "external.device_state_reported",
                device_state_to_operation,
            )

        if "automation.run" not in self.runtime.operations.list_handler_types():
            self.runtime.operations.register_handler("automation.run", handle_automation_run)

        # Подписываем обработчик события
        await self.runtime.event_bus.subscribe(
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
            await self.runtime.event_bus.unsubscribe(
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
