"""
Минимальный плагин автоматизации — очень простой и легко удаляемый.

Поведение:
- подписывается на событие `external.device_state_reported`
- проверяет, есть ли mapping для `external_id` в `runtime.state_engine` (ключ
  `devices.mapping.<external_id>`)
- если mapping найден, логирует сообщение:
  "automation: internal device <internal_id> received state change"

Ограничения:
- НЕ хранит состояния
- НЕ реализует rules engine
- НЕ использует persistence
- НЕ изменяет `devices` плагин

Все комментарии на русском языке. Файл можно удалить без побочных эффектов.
"""
from typing import Any, Dict

from plugins.base_plugin import BasePlugin, PluginMetadata


class AutomationPlugin(BasePlugin):
    """Простой плагин-реакция на изменения состояния внешнего устройства."""

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="automation",
            version="0.1.0",
            description="Минимальная automation-реакция для тестирования mapping",
            author="Home Console",
        )

    async def on_load(self) -> None:
        """Ничего не регистрируем при загрузке."""
        await super().on_load()

    async def on_start(self) -> None:
        """Подписываемся на событие и сохраняем handler для отписки."""
        await super().on_start()

        async def _handle_external_state(event_type: str, data: Dict[str, Any]):
            # Ожидаем payload с ключом external_id
            external_id = data.get("external_id")
            if not external_id:
                return

            # Получаем mapping из runtime.state_engine
            try:
                internal_id = await self.runtime.state_engine.get(f"devices.mapping.{external_id}")
            except Exception:
                # Если state_engine недоступен — ничего не делаем
                return

            # Если соответствие найдено — логируем факт получения изменения состояния
            if internal_id:
                try:
                    await self.runtime.service_registry.call(
                        "logger.log",
                        level="info",
                        message=f"automation: internal device {internal_id} received state change",
                        plugin=self.metadata.name,
                        context={"external_event": data},
                    )
                except Exception:
                    # В логах ошибок нет необходимости ломать поток
                    pass

        # Сохраняем handler чтобы отписаться при stop
        self._external_state_handler = _handle_external_state
        try:
            self.runtime.event_bus.subscribe("external.device_state_reported", self._external_state_handler)
        except Exception:
            # Подписка вспомогательная — не должна ломать старый функционал
            pass

    async def on_stop(self) -> None:
        """Отписываемся от события при остановке."""
        await super().on_stop()
        try:
            handler = getattr(self, "_external_state_handler", None)
            if handler:
                self.runtime.event_bus.unsubscribe("external.device_state_reported", handler)
        except Exception:
            pass

    async def on_unload(self) -> None:
        """Очистка ссылок на runtime при выгрузке плагина."""
        await super().on_unload()
        self.runtime = None
