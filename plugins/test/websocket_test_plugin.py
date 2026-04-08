"""
WebSocket Test Plugin для демонстрации поддержки WebSocket в HttpRegistry.

Плагин регистрирует WebSocket endpoint и простой echo handler.
"""

from sdk.plugin_ext import BasePlugin, PluginMetadata
from sdk import HttpEndpoint
from fastapi import WebSocket
from datetime import datetime, UTC


class WebSocketTestPlugin(BasePlugin):
    """
    Тестовый плагин для WebSocket.
    
    Демонстрирует:
    - регистрацию WebSocket endpoint в HttpRegistry
    - обработку WebSocket сообщений
    - корректное завершение соединения
    """

    @property
    def metadata(self) -> PluginMetadata:
        """Метаданные плагина."""
        return PluginMetadata(
            name="websocket_test",
            version="1.0.0",
            description="Тестовый плагин для WebSocket support",
            author="Home Console",
        )

    async def on_load(self) -> None:
        """Загрузка плагина."""
        await super().on_load()
        
        # Регистрируем WebSocket endpoint в HttpRegistry
        ws_endpoint = HttpEndpoint(
            path="/test/ws",
            service="websocket_test.echo",
            websocket=True,
            description="Echo WebSocket endpoint для тестирования",
            tags=["test", "websocket"]
        )
        self.register_http_endpoint(ws_endpoint)
        
        # Регистрируем сервис для обработки WebSocket соединений
        await self.register_service(
            "websocket_test.echo",
            self._websocket_echo_handler
        )

    async def on_start(self) -> None:
        """Запуск плагина."""
        await super().on_start()
        
        # Сохраняем статус в storage
        await self.storage_set(
            "websocket_test",
            "status",
            {"state": "started", "message": "WebSocket test плагин запущен"}
        )

    async def on_stop(self) -> None:
        """Остановка плагина."""
        await super().on_stop()
        
        # Обновляем статус
        await self.storage_set(
            "websocket_test",
            "status",
            {"state": "stopped", "message": "WebSocket test плагин остановлен"}
        )

    async def on_unload(self) -> None:
        """Выгрузка плагина."""
        await super().on_unload()
        
        # Удаляем сервис
        await self.unregister_service("websocket_test.echo")

    async def _websocket_echo_handler(self, websocket: WebSocket) -> None:
        """
        WebSocket handler - простой echo на сервере.
        
        Получает сообщения от клиента и отправляет их обратно.
        Закрывает соединение при получении сообщения 'close'.
        
        Args:
            websocket: FastAPI WebSocket объект
        """
        try:
            while True:
                # Получаем сообщение от клиента (текст или JSON)
                message = await websocket.receive_text()
                
                # Проверяем команду закрытия
                if message.lower() == "close":
                    await websocket.send_text("Соединение закрывается")
                    break
                
                # Echo: отправляем сообщение обратно
                response = {
                    "type": "echo",
                    "message": message,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
                await websocket.send_json(response)
                
        except Exception as e:
            import logging
            logging.error(f"WebSocket echo handler error: {str(e)}")
