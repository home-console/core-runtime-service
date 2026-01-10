"""
Базовый класс для встроенных модулей Runtime (RuntimeModule).

RuntimeModule — это обязательные домены системы, которые:
- регистрируются напрямую в CoreRuntime через ModuleManager
- не зависят от PluginManager
- используют только Core API (storage, event_bus, service_registry, state_engine)
"""

from abc import ABC, abstractmethod
from typing import Any


class RuntimeModule(ABC):
    """
    Базовый класс для встроенных модулей Runtime.

    Модули — это обязательные домены системы (devices, automation, presence),
    которые регистрируются автоматически при создании CoreRuntime.
    """

    def __init__(self, runtime: Any):
        """
        Инициализация модуля.

        Args:
            runtime: экземпляр CoreRuntime
        """
        self.runtime = runtime

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Уникальное имя модуля.

        Returns:
            имя модуля (например, "automation", "devices")
        """
        pass

    async def register(self) -> None:
        """
        Регистрация модуля в CoreRuntime.

        Выполняется при создании модуля через ModuleManager.
        Здесь регистрируются:
        - сервисы в service_registry
        - подписки на события в event_bus
        - HTTP endpoints в http_registry (опционально)

        По умолчанию — no-op. Переопределяется в подклассах.
        """
        pass

    async def start(self) -> None:
        """
        Запуск модуля.

        Вызывается при runtime.start().
        Здесь выполняется инициализация, которая требует запущенного runtime.

        По умолчанию — no-op. Переопределяется в подклассах.
        """
        pass

    async def stop(self) -> None:
        """
        Остановка модуля.

        Вызывается при runtime.stop().
        Здесь выполняется cleanup, отписка от событий и т.д.

        По умолчанию — no-op. Переопределяется в подклассах.
        """
        pass
