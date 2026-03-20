"""
EventBus - простой механизм pub/sub для событий.

Плагины могут:
- публиковать события
- подписываться на события
- НЕ знать друг о друге
"""

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


# Тип для обработчика событий
EventHandler = Callable[[str, dict[str, Any]], Awaitable[None]]


class EventBusMiddleware:
    """
    Extension point вокруг publish().

    Реализации можно использовать для метрик, трассировки, фильтрации и
    диагностики, не вмешиваясь в бизнес-обработчики событий.
    """

    async def before_publish(self, event_type: str, data: dict[str, Any]) -> None:
        pass

    async def after_publish(
        self,
        event_type: str,
        data: dict[str, Any],
        subscriber_count: int,
    ) -> None:
        pass

    async def on_handler_error(
        self,
        event_type: str,
        data: dict[str, Any],
        error: Exception,
    ) -> None:
        pass


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
        self._middleware: list[EventBusMiddleware] = []
        # Lock для thread-safety операций с _handlers
        self._lock = asyncio.Lock()

    async def add_middleware(self, middleware: EventBusMiddleware) -> None:
        """Добавить middleware для publish lifecycle."""
        async with self._lock:
            self._middleware.append(middleware)

    async def remove_middleware(self, middleware: EventBusMiddleware) -> None:
        """Удалить middleware, если он зарегистрирован."""
        async with self._lock:
            try:
                self._middleware.remove(middleware)
            except ValueError:
                pass

    async def list_middleware(self) -> list[str]:
        """Список middleware для diagnostics."""
        async with self._lock:
            return [
                getattr(m, "__class__", type(m)).__name__
                for m in self._middleware
            ]

    async def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """
        Подписаться на событие.
        
        Args:
            event_type: тип события (например, "device.state_changed")
            handler: async функция-обработчик
            
        Пример:
            async def on_state_changed(event_type: str, data: dict):
                # Обработка события
                pass
            
            await event_bus.subscribe("device.state_changed", on_state_changed)
        """
        async with self._lock:
            self._handlers[event_type].append(handler)

    async def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        """
        Отписаться от события.
        
        Args:
            event_type: тип события
            handler: обработчик для удаления
        """
        async with self._lock:
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
        # Получаем копию списка обработчиков под lock для thread-safety
        async with self._lock:
            handlers = list(self._handlers.get(event_type, []))
            middleware = list(self._middleware)

        for m in middleware:
            await m.before_publish(event_type, data)
        
        # Запускаем все обработчики параллельно
        if handlers:
            tasks = [handler(event_type, data) for handler in handlers]
            # Игнорируем ошибки в обработчиках, чтобы не падать
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Логируем ошибки в обработчиках
            for result in results:
                if isinstance(result, Exception):
                    for m in middleware:
                        await m.on_handler_error(event_type, data, result)
                    logger.warning(
                        "EventBus: ошибка в обработчике события '%s': %s",
                        event_type,
                        result,
                        exc_info=isinstance(result, BaseException),
                    )

        for m in middleware:
            await m.after_publish(event_type, data, len(handlers))

    def list_subscriptions(self) -> dict[str, list[dict[str, str]]]:
        """
        Список подписок для Inspector (read-only snapshot).
        Возвращает: event_type -> [{ "plugin": str, "handler": str }, ...].
        Если обработчик не хранит метаданные — подставляются __module__ и __qualname__.
        """
        result: dict[str, list[dict[str, str]]] = {}
        for event_type, handlers in list(self._handlers.items()):
            subs = []
            for h in handlers:
                plugin = getattr(h, "__plugin__", None) or getattr(h, "__module__", "unknown")
                handler = getattr(h, "__handler_name__", None) or getattr(h, "__name__", None) or getattr(h, "__qualname__", repr(h))
                subs.append({"plugin": str(plugin), "handler": str(handler)})
            result[event_type] = subs
        return result

    async def get_subscribers_count(self, event_type: str) -> int:
        """
        Получить количество подписчиков на событие.

        Args:
            event_type: тип события

        Returns:
            Количество подписчиков
        """
        async with self._lock:
            return len(self._handlers.get(event_type, []))

    async def clear(self) -> None:
        """Очистить все подписки."""
        async with self._lock:
            self._handlers.clear()
            self._middleware.clear()
