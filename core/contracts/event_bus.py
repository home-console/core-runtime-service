from __future__ import annotations

from typing import Any, Awaitable, Callable, Protocol


EventHandler = Callable[[dict[str, Any]], Awaitable[None]]


class EventBusInterface(Protocol):
    async def publish(
        self,
        event_or_type: dict[str, Any] | str,
        data: dict[str, Any] | None = None,
    ) -> None:
        ...

    def subscribe(
        self,
        event_type_or_handler: str | EventHandler,
        handler: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
    ) -> Awaitable[None] | None:
        ...
