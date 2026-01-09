"""
Системный плагин `automation_stub` — проверочная реализация event-driven автоматизации.

Назначение:
- подписаться на события (devices.state_changed)
- реагировать на них простым правилом
- вызвать сервисы других плагинов (logger.log)
- демонстрировать архитектуру: Event → Automation → Service → Logger

ОГРАНИЧЕНИЯ (ЗАФИКСИРОВАНЫ):
- НЕ содержит DSL, правил, конфигурации
- НЕ хранит состояние
- одно простое правило: device включён → залогировать
- взаимодействие только через runtime.event_bus и runtime.service_registry
- это STUB, не engine

Это проверка архитектуры, а не финальная автоматизация.
"""

from __future__ import annotations

from typing import Any, Callable

from plugins.base_plugin import BasePlugin, PluginMetadata


class AutomationStubPlugin(BasePlugin):
    """Проверочный плагин для event-driven автоматизации.

    Подписывается на события, реагирует простым правилом,
    логирует через runtime.service_registry.
    """

    def __init__(self, runtime):
        """Инициализация плагина с сохранением обработчика события."""
        super().__init__(runtime)
        self._event_handler: Callable | None = None

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="automation_stub",
            version="0.1.0",
            description="Stub-плагин для проверки event-driven архитектуры",
            author="Home Console",
        )

    async def on_load(self) -> None:
        """Загрузка: регистрация обработчика на `internal.device_command_requested`.

        В новой модели автоматизация реагирует на внутренние события команд.
        Правило (stub): если параметры команды содержат `on=True` — логируем.
        """
        await super().on_load()

        async def _on_device_command_requested(event_type: str, data: dict[str, Any]) -> None:
            try:
                internal_id = data.get("internal_id")
                params = data.get("params", {}) or {}

                if isinstance(params, dict) and params.get("on") is True:
                    try:
                        await self.runtime.service_registry.call(
                            "logger.log",
                            level="info",
                            message="Автоматизация: устройство включено",
                            device_id=internal_id,
                        )
                    except Exception:
                        pass

            except Exception as e:
                try:
                    await self.runtime.service_registry.call(
                        "logger.log",
                        level="error",
                        message=f"Ошибка в автоматизации: {str(e)}",
                        plugin=self.metadata.name,
                    )
                except Exception:
                    pass

        self._event_handler = _on_device_command_requested
        try:
            self.runtime.event_bus.subscribe("internal.device_command_requested", self._event_handler)
        except Exception:
            pass

    async def on_start(self) -> None:
        """Запуск: логирование включения автоматизации."""
        await super().on_start()
        # Логируем запуск автоматизации
        try:
            await self.runtime.service_registry.call(
                "logger.log",
                level="info",
                message="Автоматизация запущена",
                plugin=self.metadata.name,
            )
        except Exception:
            # Не мешаем запуску системы при ошибках логирования
            pass

    async def on_stop(self) -> None:
        """Остановка: отписка от событий и логирование."""
        await super().on_stop()
        # Отписываемся от события
        try:
            if self._event_handler is not None:
                # unsubscribe from the same event we subscribed to in on_load
                self.runtime.event_bus.unsubscribe("internal.device_command_requested", self._event_handler)
        except Exception:
            pass

        # Логируем остановку
        try:
            await self.runtime.service_registry.call(
                "logger.log",
                level="info",
                message="Автоматизация остановлена",
                plugin=self.metadata.name,
            )
        except Exception:
            pass

    async def on_unload(self) -> None:
        """Выгрузка: очистка ссылок."""
        await super().on_unload()
        # Очищаем ссылку на обработчик
        self._event_handler = None
