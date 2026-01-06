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

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="automation_stub",
            version="0.1.0",
            description="Stub-плагин для проверки event-driven архитектуры",
            author="Home Console",
        )

    async def on_load(self) -> None:
        await super().on_load()
        # Сохраняем runtime для доступа к event_bus и service_registry
        self._runtime = self.runtime
        self._event_handler: Callable | None = None

        # Создаём обработчик события devices.state_changed
        async def _on_device_state_changed(
            event_type: str, data: dict[str, Any]
        ) -> None:
            """Обработчик события изменения состояния устройства.

            Простое правило:
            ЕСЛИ new_state.power == "on" → залогировать через logger.log
            """
            try:
                device_id = data.get("device_id")
                new_state = data.get("new_state", {})

                # Простая проверка: если state содержит power="on"
                if isinstance(new_state, dict) and new_state.get("power") == "on":
                    # Вызываем logger.log через service registry
                    try:
                        await self.runtime.service_registry.call(
                            "logger.log",
                            level="info",
                            message="Automation: устройство включено",
                            device_id=device_id,
                        )
                    except Exception as e:
                        # Если logger недоступен — игнорируем (ошибка не должна ломать event loop)
                        pass

            except Exception as e:
                # Исключения обработчика НЕ должны падать в Core
                # Пробуем залогировать, но не требуем успеха
                try:
                    await self.runtime.service_registry.call(
                        "logger.log",
                        level="error",
                        message=f"Automation error: {str(e)}",
                    )
                except Exception:
                    pass

        # Сохраняем обработчик, чтобы можно было отписаться позже
        self._event_handler = _on_device_state_changed

        # Подписываемся на событие devices.state_changed
        try:
            self.runtime.event_bus.subscribe("devices.state_changed", self._event_handler)
        except Exception:
            # Если подписка не удалась — это не должно ломать загрузку плагина
            pass

    async def on_start(self) -> None:
        await super().on_start()
        # Логируем запуск автоматизации
        try:
            await self.runtime.service_registry.call(
                "logger.log",
                level="info",
                message="automation_stub запущен",
                plugin=self.metadata.name,
            )
        except Exception:
            # Не мешаем запуску системы при ошибках логирования
            pass

    async def on_stop(self) -> None:
        await super().on_stop()
        # Отписываемся от события
        try:
            if self._event_handler is not None:
                self.runtime.event_bus.unsubscribe("devices.state_changed", self._event_handler)
        except Exception:
            pass

        # Логируем остановку
        try:
            await self.runtime.service_registry.call(
                "logger.log",
                level="info",
                message="automation_stub остановлен",
                plugin=self.metadata.name,
            )
        except Exception:
            pass

    async def on_unload(self) -> None:
        await super().on_unload()
        # Очищаем ссылки
        try:
            self._event_handler = None
            self._runtime = None
            self.runtime = None
        except Exception:
            pass
