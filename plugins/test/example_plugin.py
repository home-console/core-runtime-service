"""
Пример плагина для демонстрации работы Core Runtime.

Этот плагин показывает, как создавать свои плагины.
"""

from core.kernel.base_plugin import BasePlugin, PluginMetadata


class ExamplePlugin(BasePlugin):
    """
    Пример простого плагина.
    
    Демонстрирует:
    - регистрацию сервиса
    - подписку на события
    - работу с storage
    """

    @property
    def metadata(self) -> PluginMetadata:
        """Метаданные плагина."""
        return PluginMetadata(
            name="example",
            version="1.0.0",
            description="Пример плагина для демонстрации",
            author="Home Console",
        )

    async def on_load(self) -> None:
        """Загрузка плагина."""
        await super().on_load()
        
        # Регистрируем сервис
        await self.register_service(
            "example.hello",
            self._hello_service
        )
        
        # Подписываемся на событие
        await self.subscribe_event(
            "example.test",
            self._on_test_event
        )

    async def on_start(self) -> None:
        """Запуск плагина."""
        await super().on_start()
        
        # Сохраняем что-то в storage
        await self.storage_set(
            "example",
            "status",
            {"state": "started", "message": "Плагин запущен"}
        )

    async def on_stop(self) -> None:
        """Остановка плагина."""
        await super().on_stop()
        
        # Обновляем статус
        await self.storage_set(
            "example",
            "status",
            {"state": "stopped", "message": "Плагин остановлен"}
        )

    async def on_unload(self) -> None:
        """Выгрузка плагина."""
        await super().on_unload()
        
        # Удаляем сервис
        await self.unregister_service("example.hello")
        
        # Отписываемся от событий
        await self.unsubscribe_event(
            "example.test",
            self._on_test_event
        )

    async def _hello_service(self, name: str) -> str:
        """
        Пример сервиса.
        
        Args:
            name: имя для приветствия
            
        Returns:
            Приветствие
        """
        return f"Привет, {name}!"

    async def _on_test_event(self, event_type: str, data: dict) -> None:
        """
        Обработчик тестового события.
        
        Args:
            event_type: тип события
            data: данные события
        """
        try:
            await self.call_service(
                "logger.log",
                level="info",
                message=f"Получено событие {event_type}",
                plugin="example",
                event_data=data
            )
        except Exception:
            # Не ломаем обработку события при ошибках логирования
            pass
