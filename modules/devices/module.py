"""
DevicesModule — встроенный модуль управления устройствами.

Обязательный домен системы, который регистрируется автоматически
при создании CoreRuntime через ModuleManager.
"""

from core.runtime_module import RuntimeModule
from . import services, handlers


class DevicesModule(RuntimeModule):
    """
    Модуль управления устройствами.

    Регистрирует сервисы для работы с устройствами и подписывается
    на события внешних устройств.
    """

    @property
    def name(self) -> str:
        """Уникальное имя модуля."""
        return "devices"

    async def register(self) -> None:
        """
        Регистрация модуля в CoreRuntime.

        Регистрирует сервисы и подписывается на события.
        """
        # Регистрация сервисов
        service_names = [
            ("devices.list", services.list_devices),
            ("devices.get", services.get_device),
            ("devices.create", services.create_device),
            ("devices.set_state", services.set_state),
            ("devices.list_external", services.list_external),
            ("devices.create_mapping", services.create_mapping),
            ("devices.list_mappings", services.list_mappings),
            ("devices.delete_mapping", services.delete_mapping),
            ("devices.auto_map_external", services.auto_map_external),
        ]

        self._registered_services = []

        for name, func in service_names:
            # Skip services that are already registered (idempotent)
            try:
                if await self.runtime.service_registry.has_service(name):
                    continue
            except Exception:
                # If service_registry doesn't implement has_service for some reason,
                # fall back to attempting registration and catching ValueError below.
                pass

            async def _wrapper(*args, _func=func, **kwargs):
                return await _func(self.runtime, *args, **kwargs)

            try:
                await self.runtime.service_registry.register(name, _wrapper)
                self._registered_services.append(name)
            except ValueError:
                # already registered concurrently — skip
                continue

        # Подписка на события
        await self.runtime.event_bus.subscribe(
            "external.device_state_reported",
            self._handle_external_state
        )
        await self.runtime.event_bus.subscribe(
            "external.device_discovered",
            self._handle_external_device_discovered
        )

    async def start(self) -> None:
        """
        Запуск модуля.

        В текущей реализации devices не требует инициализации при старте.
        """
        pass

    async def stop(self) -> None:
        """
        Остановка модуля.

        Отписывается от событий и отменяет регистрацию сервисов.
        """
        # Отписка от событий
        try:
            await self.runtime.event_bus.unsubscribe(
                "external.device_state_reported",
                self._handle_external_state
            )
        except Exception:
            pass

        try:
            await self.runtime.event_bus.unsubscribe(
                "external.device_discovered",
                self._handle_external_device_discovered
            )
        except Exception:
            pass

        # Отмена регистрации сервисов
        for service_name in getattr(self, "_registered_services", []):
            try:
                await self.runtime.service_registry.unregister(service_name)
            except Exception:
                pass

    async def _handle_external_state(self, event_type: str, data: dict) -> None:
        """Обработчик события external.device_state_reported."""
        await handlers.handle_external_state(self.runtime, data)

    async def _handle_external_device_discovered(self, event_type: str, data: dict) -> None:
        """Обработчик события external.device_discovered."""
        await handlers.handle_external_device_discovered(self.runtime, data)
