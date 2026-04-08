from __future__ import annotations

import asyncio
import inspect
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, cast

from core.messaging_claim_manager import EventBusClaimManager
from core.messaging_storage import EventBusStorageManager

logger = logging.getLogger(__name__)


@dataclass
class Event:
    id: str
    type: str
    payload: dict[str, Any]
    created_at: float
    claim_ttl: float = 30.0
    processed: bool = False
    processed_at: float | None = None
    claimed_by: str | None = None
    claimed_at: float | None = None

    @classmethod
    def new(cls, event_type: str, payload: dict[str, Any]) -> "Event":
        return cls(
            id=f"evt-{uuid.uuid4().hex}",
            type=str(event_type),
            payload=dict(payload),
            created_at=time.time(),
            claim_ttl=30.0,
            processed=False,
            processed_at=None,
            claimed_by=None,
            claimed_at=None,
        )

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Event":
        return cls(
            id=str(value.get("id") or f"evt-{uuid.uuid4().hex}"),
            type=str(value.get("type") or ""),
            payload=dict(value.get("payload") or {}),
            created_at=float(value.get("created_at") or time.time()),
            claim_ttl=float(value.get("claim_ttl") or 30.0),
            processed=bool(value.get("processed", False)),
            processed_at=(
                float(value["processed_at"])
                if value.get("processed_at") is not None
                else None
            ),
            claimed_by=(
                str(value["claimed_by"])
                if value.get("claimed_by") is not None
                else None
            ),
            claimed_at=(
                float(value["claimed_at"])
                if value.get("claimed_at") is not None
                else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "payload": dict(self.payload),
            "created_at": float(self.created_at),
            "claim_ttl": float(self.claim_ttl),
            "processed": bool(self.processed),
            "processed_at": self.processed_at,
            "claimed_by": self.claimed_by,
            "claimed_at": self.claimed_at,
        }


TypedEventHandler = Callable[[str, dict[str, Any]], Awaitable[None]]
SimpleEventHandler = Callable[[dict[str, Any]], Awaitable[None]]
AnyEventHandler = Callable[..., Awaitable[None]]


class EventBusMiddleware:
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


class _CompletedAwaitable:
    def __await__(self):
        if False:
            yield None
        return None


class InMemoryEventBus:
    def __init__(
        self,
        storage: Any | None = None,
        max_concurrent_handlers: int = 100,
    ) -> None:
        # Делегирование специализированным компонентам (SRP)
        self._storage_manager = EventBusStorageManager(storage)
        self._claim_manager = EventBusClaimManager(storage)

        # Per-instance backpressure semaphore (не глобальный синглтон)
        self._handler_semaphore = asyncio.Semaphore(max_concurrent_handlers)

        # Pub/Sub компоненты
        self._handlers: dict[str, list[TypedEventHandler]] = defaultdict(list)
        # Original handler -> wrapped typed handler (for unsubscribe support).
        self._handler_wrappers: dict[tuple[str, AnyEventHandler], TypedEventHandler] = {}
        self._middleware: list[EventBusMiddleware] = []
        self._lock = asyncio.Lock()

    def _wrap_handler(self, event_type: str, handler: AnyEventHandler) -> TypedEventHandler:
        """
        Нормализовать handler к единому typed-контракту.

        Поддерживает:
        - async handler(event_type, payload)
        - async handler(payload)  (payload будет содержать payload["type"])
        """
        cached = self._handler_wrappers.get((event_type, handler))
        if cached is not None:
            return cached

        params_count = 2
        try:
            params_count = len(inspect.signature(handler).parameters)
        except (TypeError, ValueError):
            params_count = 2

        if params_count <= 1:
            simple_handler = cast(SimpleEventHandler, handler)

            async def _adapter(_event_type: str, data: dict[str, Any]) -> None:
                payload: dict[str, Any] = dict(data)
                payload.setdefault("type", _event_type)
                await simple_handler(payload)

            wrapped = cast(TypedEventHandler, _adapter)
        else:
            wrapped = cast(TypedEventHandler, handler)

        self._handler_wrappers[(event_type, handler)] = wrapped
        return wrapped

    async def _save_event(self, event: Event) -> None:
        """Делегирует EventBusStorageManager."""
        await self._storage_manager.save_event(event.to_dict())

    async def get_unprocessed_events(self) -> list[dict[str, Any]]:
        """Делегирует EventBusStorageManager."""
        return await self._storage_manager.get_unprocessed_events()

    async def is_event_processed(self, event_id: str) -> bool:
        """Делегирует EventBusStorageManager."""
        return await self._storage_manager.is_event_processed(event_id)

    async def mark_event_processed(self, event_id: str) -> None:
        """Делегирует EventBusStorageManager."""
        await self._storage_manager.mark_event_processed(event_id)

    async def claim_event(self, event_id: str, worker_id: str) -> bool:
        """Делегирует EventBusClaimManager."""
        return await self._claim_manager.claim_event(event_id, worker_id)

    async def add_middleware(self, middleware: EventBusMiddleware) -> None:
        async with self._lock:
            self._middleware.append(middleware)

    async def remove_middleware(self, middleware: EventBusMiddleware) -> None:
        async with self._lock:
            try:
                self._middleware.remove(middleware)
            except ValueError:
                pass

    async def list_middleware(self) -> list[str]:
        async with self._lock:
            return [getattr(m, "__class__", type(m)).__name__ for m in self._middleware]

    def subscribe(
        self,
        event_type_or_handler: str | AnyEventHandler,
        handler: AnyEventHandler | None = None,
    ) -> _CompletedAwaitable:
        if isinstance(event_type_or_handler, str):
            if handler is None:
                return _CompletedAwaitable()
            wrapped = self._wrap_handler(event_type_or_handler, handler)
            self._handlers[event_type_or_handler].append(wrapped)
            return _CompletedAwaitable()

        event_type = "*"
        wrapped = self._wrap_handler(event_type, event_type_or_handler)
        self._handlers[event_type].append(wrapped)
        return _CompletedAwaitable()

    def unsubscribe(
        self, event_type: str, handler: AnyEventHandler
    ) -> _CompletedAwaitable:
        if event_type in self._handlers:
            wrapped = self._handler_wrappers.get((event_type, handler))
            try:
                self._handlers[event_type].remove(
                    cast(TypedEventHandler, wrapped or handler)
                )
            except ValueError:
                pass
        return _CompletedAwaitable()

    async def publish(
        self,
        event_or_type: dict[str, Any] | str,
        data: dict[str, Any] | None = None,
    ) -> None:
        if isinstance(event_or_type, dict):
            event_type = str(event_or_type.get("type") or "")
            payload = dict(event_or_type)
            event_id = str(payload.pop("id", "") or "")
            payload.pop("type", None)
        else:
            event_type = str(event_or_type)
            payload = dict(data or {})
            event_id = ""

        if not event_type:
            return

        event = Event.new(event_type=event_type, payload=payload)
        if event_id:
            event.id = event_id
        await self._save_event(event)

        payload_with_meta = dict(payload)
        payload_with_meta["id"] = event.id
        # Homogenize handler payload shape:
        # typed handlers now also receive payload["type"].
        payload_with_meta["type"] = event_type

        async with self._lock:
            handlers = list(self._handlers.get(event_type, []))
            handlers.extend(self._handlers.get("*", []))
            middleware = list(self._middleware)

        for item in middleware:
            await item.before_publish(event_type, payload_with_meta)

        if handlers:
            async def run_with_backpressure(handler):
                async with self._handler_semaphore:
                    return await handler(event_type, payload_with_meta)
            
            tasks = [run_with_backpressure(handler) for handler in handlers]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    for item in middleware:
                        await item.on_handler_error(
                            event_type, payload_with_meta, result
                        )
                    logger.warning(
                        "EventBus: handler error for event '%s': %s",
                        event_type,
                        result,
                        exc_info=True,
                    )

        for item in middleware:
            await item.after_publish(event_type, payload_with_meta, len(handlers))

    def list_subscriptions(self) -> dict[str, list[dict[str, str]]]:
        result: dict[str, list[dict[str, str]]] = {}
        for event_type, handlers in list(self._handlers.items()):
            subs: list[dict[str, str]] = []
            for handler in handlers:
                plugin = getattr(handler, "__plugin__", None) or getattr(
                    handler, "__module__", "unknown"
                )
                handler_name = (
                    getattr(handler, "__handler_name__", None)
                    or getattr(handler, "__name__", None)
                    or getattr(handler, "__qualname__", repr(handler))
                )
                subs.append({"plugin": str(plugin), "handler": str(handler_name)})
            result[event_type] = subs
        return result

    async def get_subscribers_count(self, event_type: str) -> int:
        async with self._lock:
            return len(self._handlers.get(event_type, []))

    async def clear(self) -> None:
        async with self._lock:
            self._handlers.clear()
            self._middleware.clear()
            self._handler_wrappers.clear()
