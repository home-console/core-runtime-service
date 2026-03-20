"""
Быстрый пример: WebSocket endpoint в плагине

Этот файл показывает полный пример создания WebSocket endpoint
в плагине для Home Console.
"""

from core.kernel.base_plugin import BasePlugin, PluginMetadata
from core.http_registry import HttpEndpoint
from fastapi import WebSocket
import json
import logging
from datetime import datetime, UTC

logger = logging.getLogger(__name__)


class ChatPluginExample(BasePlugin):
    """
    Пример плагина: простой WebSocket чат.
    
    Подключение:
        ws://localhost:8000/api/chat/ws
    
    Команды:
        {"action": "send", "message": "Hello"}  -> Echo сообщение
        {"action": "ping"}                      -> Получить pong
        {"action": "disconnect"}                -> Закрыть соединение
    """

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="chat_example",
            version="1.0.0",
            description="WebSocket chat пример",
            author="User",
        )

    async def on_load(self) -> None:
        """Регистрируем WebSocket endpoint и сервис."""
        await super().on_load()
        
        # Регистрируем WebSocket endpoint
        ws_endpoint = HttpEndpoint(
            path="/api/chat/ws",
            service="chat_example.websocket",
            websocket=True,
            description="Простой WebSocket чат для демонстрации",
            tags=["example", "websocket", "chat"]
        )
        self.runtime.http.register(ws_endpoint)
        
        # Регистрируем сервис для обработки
        await self.runtime.service_registry.register(
            "chat_example.websocket",
            self._websocket_handler
        )
        
        logger.info("Chat WebSocket endpoint зарегистрирован на /api/chat/ws")

    async def on_start(self) -> None:
        """Плагин запущен."""
        await super().on_start()
        await self.runtime.storage.set(
            "chat_example",
            "status",
            {"state": "active"}
        )

    async def on_unload(self) -> None:
        """Очищаем при выгрузке."""
        await super().on_unload()
        await self.runtime.service_registry.unregister("chat_example.websocket")

    async def _websocket_handler(self, websocket: WebSocket) -> None:
        """
        Главный WebSocket handler.
        
        Принимает JSON сообщения и отвечает на них.
        """
        await websocket.accept()
        client_id = None
        
        try:
            while True:
                # Получаем данные от клиента
                data = await websocket.receive_json()
                action = data.get("action", "unknown")
                
                logger.info(f"WebSocket message: action={action}")
                
                # Обрабатываем команды
                if action == "send":
                    message = data.get("message", "")
                    response = {
                        "type": "message",
                        "echo": message,
                        "timestamp": datetime.now(UTC).isoformat(),
                        "server": "Chat Example",
                    }
                    await websocket.send_json(response)
                
                elif action == "ping":
                    await websocket.send_json({
                        "type": "pong",
                        "timestamp": datetime.now(UTC).isoformat(),
                    })
                
                elif action == "set_id":
                    client_id = data.get("id", "unknown")
                    await websocket.send_json({
                        "type": "id_set",
                        "id": client_id,
                    })
                
                elif action == "disconnect":
                    await websocket.send_json({
                        "type": "goodbye",
                        "message": "Вы отключаетесь",
                    })
                    break
                
                else:
                    await websocket.send_json({
                        "type": "error",
                        "error": f"Unknown action: {action}",
                    })
        
        except Exception as e:
            logger.error(f"WebSocket error: {str(e)}")
            try:
                await websocket.close(code=1011, reason=str(e))
            except Exception:
                pass


# ============================================================================
# КЛИЕНТСКИЙ КОД ДЛЯ ТЕСТИРОВАНИЯ
# ============================================================================

if __name__ == "__main__":
    """
    Использование:
        python chat_example.py
    
    Требуется:
        - pip install websockets
    """
    import websockets

    async def test_websocket():
        """Тестируем WebSocket с сервера."""
        # Подключаемся к серверу
        async with websockets.connect("ws://localhost:8000/api/chat/ws") as ws:
            print("✓ Подключены к WebSocket")
            
            # Отправляем ping
            await ws.send(json.dumps({"action": "ping"}))
            response = await ws.recv()
            print(f"← Ping response: {response}")
            
            # Отправляем сообщение
            await ws.send(json.dumps({
                "action": "send",
                "message": "Привет, сервер!"
            }))
            response = await ws.recv()
            print(f"← Echo response: {response}")
            
            # Отправляем ID
            await ws.send(json.dumps({
                "action": "set_id",
                "id": "client-001"
            }))
            response = await ws.recv()
            print(f"← ID response: {response}")
            
            # Отключаемся
            await ws.send(json.dumps({"action": "disconnect"}))
            response = await ws.recv()
            print(f"← Goodbye: {response}")

    print("WebSocket Chat Example")
    print("=" * 50)
    print("Для использования:")
    print("1. Запустите Home Console сервер:")
    print("   python main.py")
    print()
    print("2. Запустите тест:")
    print("   python -m asyncio chat_example.py")
    print()
    print("Или используйте JavaScript WebSocket клиент:")
    print("""
    const ws = new WebSocket('ws://localhost:8000/api/chat/ws');
    ws.onopen = () => {
        ws.send(JSON.stringify({action: 'ping'}));
    };
    ws.onmessage = (event) => {
        console.log('Server:', event.data);
    };
    """)
