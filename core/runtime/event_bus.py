from __future__ import annotations

from typing import Any, Awaitable, Callable


EventHandler = Callable[[dict[str, Any]], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self.subscribers: list[EventHandler] = []

    async def publish(self, event: dict[str, Any]) -> None:
        for subscriber in list(self.subscribers):
            await subscriber(event)

    def subscribe(self, handler: EventHandler) -> None:
        self.subscribers.append(handler)
