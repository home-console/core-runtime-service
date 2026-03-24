from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections import defaultdict
from typing import Any, Awaitable, Callable, cast

from .models import Event

logger = logging.getLogger(__name__)


TypedEventHandler = Callable[[str, dict[str, Any]], Awaitable[None]]
SimpleEventHandler = Callable[[dict[str, Any]], Awaitable[None]]


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
    def __init__(self, storage: Any | None = None) -> None:
        self._storage = storage
        self._handlers: dict[str, list[TypedEventHandler]] = defaultdict(list)
        self._middleware: list[EventBusMiddleware] = []
        self._lock = asyncio.Lock()

    async def _save_event(self, event: Event) -> None:
        if self._storage is None:
            return
        save = getattr(self._storage, "set", None)
        if not callable(save):
            return
        outcome = save("event_bus_events", event.id, event.to_dict())
        if inspect.isawaitable(outcome):
            await outcome

    async def get_unprocessed_events(self) -> list[dict[str, Any]]:
        if self._storage is None:
            return []

        list_keys = getattr(self._storage, "list_keys", None)
        get = getattr(self._storage, "get", None)
        if not callable(list_keys) or not callable(get):
            return []

        keys_outcome = list_keys("event_bus_events")
        keys_value = (
            await keys_outcome if inspect.isawaitable(keys_outcome) else keys_outcome
        )
        if not isinstance(keys_value, list):
            return []

        keys_list = [str(key) for key in cast(list[Any], keys_value)]

        events: list[Event] = []
        for event_id in keys_list:
            raw_outcome = get("event_bus_events", event_id)
            raw = await raw_outcome if inspect.isawaitable(raw_outcome) else raw_outcome
            if not isinstance(raw, dict):
                continue
            event = Event.from_dict(cast(dict[str, Any], raw))
            if not event.processed:
                events.append(event)

        events.sort(key=lambda item: item.created_at)
        return [item.to_dict() for item in events]

    async def is_event_processed(self, event_id: str) -> bool:
        if self._storage is None:
            return False

        get = getattr(self._storage, "get", None)
        if not callable(get):
            return False

        raw_outcome = get("event_bus_events", event_id)
        raw = await raw_outcome if inspect.isawaitable(raw_outcome) else raw_outcome
        if not isinstance(raw, dict):
            return False

        event = Event.from_dict(cast(dict[str, Any], raw))
        return bool(event.processed)

    async def mark_event_processed(self, event_id: str) -> None:
        if self._storage is None:
            return

        get = getattr(self._storage, "get", None)
        save = getattr(self._storage, "set", None)
        if not callable(get) or not callable(save):
            return

        raw_outcome = get("event_bus_events", event_id)
        raw = await raw_outcome if inspect.isawaitable(raw_outcome) else raw_outcome
        if not isinstance(raw, dict):
            return

        event = Event.from_dict(cast(dict[str, Any], raw))
        event.processed = True
        event.processed_at = time.time()
        event.claimed_by = None
        event.claimed_at = None

        save_outcome = save("event_bus_events", event_id, event.to_dict())
        if inspect.isawaitable(save_outcome):
            await save_outcome

    async def _claim_event_sqlite_atomic(
        self, adapter: Any, event_id: str, worker_id: str
    ) -> bool:
        run_atomic = getattr(adapter, "run_atomic", None)
        if not callable(run_atomic):
            return False

        now = time.time()

        def _sync_claim(conn: Any, _adapter: Any) -> bool:
            cursor = conn.execute(
                """
                UPDATE storage
                SET value = json_set(
                    json_set(value, '$.claimed_by', ?),
                    '$.claimed_at', ?
                )
                WHERE namespace = ?
                  AND key = ?
                  AND COALESCE(json_extract(value, '$.processed'), 0) = 0
                  AND (
                        json_extract(value, '$.claimed_by') IS NULL
                     OR json_extract(value, '$.claimed_by') = ?
                     OR (
                            ? - COALESCE(json_extract(value, '$.claimed_at'), 0.0)
                          ) > COALESCE(json_extract(value, '$.claim_ttl'), 60.0)
                  )
                """,
                (
                    worker_id,
                    now,
                    "event_bus_events",
                    event_id,
                    worker_id,
                    now,
                ),
            )
            return cursor.rowcount > 0

        result = run_atomic(_sync_claim)
        return await result if inspect.isawaitable(result) else bool(result)

    async def _claim_event_postgresql_atomic(
        self, adapter: Any, event_id: str, worker_id: str
    ) -> bool:
        get_pool = getattr(adapter, "_get_pool", None)
        if not callable(get_pool):
            return False

        pool = get_pool()
        pool_value = cast(Any, await pool if inspect.isawaitable(pool) else pool)
        if pool_value is None:
            return False

        now = time.time()
        async with pool_value.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE storage
                SET value = jsonb_set(
                    jsonb_set(value, '{claimed_by}', to_jsonb($3::text), true),
                    '{claimed_at}',
                    to_jsonb($4::double precision),
                    true
                )
                WHERE namespace = $1
                  AND key = $2
                  AND COALESCE((value ->> 'processed')::boolean, false) = false
                  AND (
                        value ->> 'claimed_by' IS NULL
                     OR value ->> 'claimed_by' = $3
                     OR (
                            $4 - COALESCE((value ->> 'claimed_at')::double precision, 0.0)
                          ) > COALESCE((value ->> 'claim_ttl')::double precision, 60.0)
                  )
                RETURNING 1
                """,
                "event_bus_events",
                event_id,
                worker_id,
                now,
            )
            return row is not None

    async def _claim_event_fallback(self, event_id: str, worker_id: str) -> bool:
        get = getattr(self._storage, "get", None)
        save = getattr(self._storage, "set", None)
        if not callable(get) or not callable(save):
            return True

        raw_outcome = get("event_bus_events", event_id)
        raw = await raw_outcome if inspect.isawaitable(raw_outcome) else raw_outcome
        if not isinstance(raw, dict):
            return False

        event = Event.from_dict(cast(dict[str, Any], raw))
        now = time.time()
        if event.processed:
            return False
        if event.claimed_by is not None and event.claimed_by != worker_id:
            claimed_at = float(event.claimed_at or 0.0)
            if now - claimed_at <= float(event.claim_ttl):
                return False

        event.claimed_by = worker_id
        event.claimed_at = now
        save_outcome = save("event_bus_events", event_id, event.to_dict())
        if inspect.isawaitable(save_outcome):
            await save_outcome
        return True

    async def claim_event(self, event_id: str, worker_id: str) -> bool:
        if self._storage is None:
            return True

        adapter = getattr(self._storage, "_adapter", None)
        adapter_name = type(adapter).__name__.lower() if adapter is not None else ""

        if "sqlite" in adapter_name:
            return await self._claim_event_sqlite_atomic(adapter, event_id, worker_id)

        if "postgres" in adapter_name:
            return await self._claim_event_postgresql_atomic(
                adapter, event_id, worker_id
            )

        return await self._claim_event_fallback(event_id, worker_id)

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
        event_type_or_handler: str | SimpleEventHandler,
        handler: TypedEventHandler | None = None,
    ) -> _CompletedAwaitable:
        if isinstance(event_type_or_handler, str):
            if handler is None:
                return _CompletedAwaitable()
            self._handlers[event_type_or_handler].append(handler)
            return _CompletedAwaitable()

        event_type = "*"
        simple_handler = event_type_or_handler

        async def _adapter(_event_type: str, data: dict[str, Any]) -> None:
            payload: dict[str, Any] = {"type": _event_type, **data}
            await simple_handler(payload)

        self._handlers[event_type].append(_adapter)
        return _CompletedAwaitable()

    def unsubscribe(
        self, event_type: str, handler: TypedEventHandler
    ) -> _CompletedAwaitable:
        if event_type in self._handlers:
            try:
                self._handlers[event_type].remove(handler)
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

        event = Event.new(event_type=event_type, payload=payload)
        if event_id:
            event.id = event_id
        await self._save_event(event)

        payload_with_meta = dict(payload)
        payload_with_meta["id"] = event.id

        async with self._lock:
            handlers = list(self._handlers.get(event_type, []))
            handlers.extend(self._handlers.get("*", []))
            middleware = list(self._middleware)

        for item in middleware:
            await item.before_publish(event_type, payload_with_meta)

        if handlers:
            tasks = [handler(event_type, payload_with_meta) for handler in handlers]
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
