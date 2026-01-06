"""
EventBus - простой механизм pub/sub для событий.

Плагины могут:
- публиковать события
- подписываться на события
- НЕ знать друг о друге
"""

import asyncio
from collections import defaultdict
from typing import Any, Callable, Awaitable


# Тип для обработчика событий
EventHandler = Callable[[str, dict[str, Any]], Awaitable[None]]


class EventBus:
    """
    Простая шина событий для обмена сообщениями между плагинами.
    
    Принцип работы:
    - плагины публикуют события с типом и данными
    - другие плагины подписываются на типы событий
    - EventBus маршрутизирует события к подписчикам
    """

    def __init__(self):
        # Словарь: event_type -> list[handler]
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """
        Подписаться на событие.
        
        Args:
            event_type: тип события (например, "device.state_changed")
            handler: async функция-обработчик
            
        Пример:
            async def on_state_changed(event_type: str, data: dict):
                print(f"Device changed: {data}")
            
            event_bus.subscribe("device.state_changed", on_state_changed)
        """
        self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        """
        Отписаться от события.
        
        Args:
            event_type: тип события
            handler: обработчик для удаления
        """
        if event_type in self._handlers:
            try:
                self._handlers[event_type].remove(handler)
            except ValueError:
                pass

    async def publish(self, event_type: str, data: dict[str, Any]) -> None:
        """
        Опубликовать событие.
        
        Args:
            event_type: тип события
            data: данные события
            
        Пример:
            await event_bus.publish("device.state_changed", {
                "device_id": "lamp_kitchen",
                "state": "on"
            })
        """
        handlers = self._handlers.get(event_type, [])
        
        # Запускаем все обработчики параллельно
        if handlers:
            tasks = [handler(event_type, data) for handler in handlers]
            # Игнорируем ошибки в обработчиках, чтобы не падать
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Логируем ошибки (если нужно)
            for result in results:
                if isinstance(result, Exception):
                    # TODO: добавить логирование
                    pass

    def get_subscribers_count(self, event_type: str) -> int:
        """
        Получить количество подписчиков на событие.
        
        Args:
            event_type: тип события
            
        Returns:
            Количество подписчиков
        """
        return len(self._handlers.get(event_type, []))

    def clear(self) -> None:
        """Очистить все подписки."""
        self._handlers.clear()
