"""
RedisStreamsEventBus — реализация IEventBus через Redis Streams.

Обеспечивает:
- pub/sub через Redis Streams (XADD / XREADGROUP)
- Exactly-once семантику через consumer groups + XACK (best-effort in v1)
- Автоматическое создание consumer groups при старте/публикации
- Совместимость с IEventBus Protocol (drop-in замена InMemoryEventBus)
- Локальный dispatch: события публикуются в Redis и доставляются
  локальным подписчикам без дополнительного round-trip

Не обеспечивает:
- Совместимость с EventBusClaimManager (Redis Streams — своя семантика)

Зависимости: redis[asyncio] (redis-py async client)
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import uuid
from typing import Any

from core.messaging import AnyEventHandler, resolve_max_concurrent_handlers

logger = logging.getLogger(__name__)

STREAM_PREFIX = "hc:events:"  # ключ в Redis: hc:events:{event_type}
CONSUMER_GROUP = "core-runtime"  # имя consumer group
CONSUMER_NAME_PREFIX = "worker"  # имя consumer в группе


class RedisStreamsEventBus:
    """
    IEventBus через Redis Streams.

    Использование:
        bus = RedisStreamsEventBus(redis_url="redis://localhost:6379")
        await bus.start()
        bus.subscribe("devices.state_changed", handler)
        await bus.publish("devices.state_changed", {"device_id": "abc"})
        await bus.stop()
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        consumer_name: str | None = None,
        max_len: int = 10_000,
        block_ms: int = 1_000,
        batch_size: int = 10,
        storage: Any = None,  # совместимость с InMemoryEventBus signature
        max_concurrent_handlers: int | None = None,
    ) -> None:
        self._redis_url = redis_url
        self._consumer_name = consumer_name or (
            f"{CONSUMER_NAME_PREFIX}-{uuid.uuid4().hex[:8]}"
        )
        self._max_len = int(max_len)
        self._block_ms = int(block_ms)
        self._batch_size = int(batch_size)
        self._storage = storage  # не используется, для совместимости
        limit = resolve_max_concurrent_handlers(max_concurrent_handlers)
        self._handler_semaphore = asyncio.Semaphore(limit)

        self._redis: Any = None  # redis.asyncio.Redis
        self._subscribers: dict[str, list[AnyEventHandler]] = {}
        self._middleware: list[Any] = []
        self._reader_task: asyncio.Task[None] | None = None
        self._running = False
        self._processed_events: set[str] = set()  # локальный dedup
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Подключиться к Redis и запустить reader loop."""
        try:
            import redis.asyncio as aioredis
        except ImportError as e:
            raise ImportError(
                "redis[asyncio] required for RedisStreamsEventBus. "
                "Run: pip install 'redis[asyncio]'"
            ) from e

        self._redis = await aioredis.from_url(
            self._redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        self._running = True
        self._reader_task = asyncio.create_task(
            self._reader_loop(), name="redis-eventbus-reader"
        )
        logger.info("[RedisEventBus] Connected to %s", self._redis_url)

    async def stop(self) -> None:
        """Остановить reader и закрыть соединение."""
        self._running = False
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
        logger.info("[RedisEventBus] Stopped")

    async def clear(self) -> None:
        """
        RuntimeLifecycleMixin.shutdown() вызывает event_bus.clear().
        Для Redis backend это noop (подписки и потоки не трогаем).
        """

    # ─── IEventBus interface ────────────────────────────────────────

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        """Опубликовать событие: XADD в Redis + локальная доставка."""
        event_type = str(event_type)
        if not event_type:
            return

        event_id = str(uuid.uuid4())
        stream_key = f"{STREAM_PREFIX}{event_type}"

        data = {
            "event_id": event_id,
            "event_type": event_type,
            "payload": json.dumps(payload),
        }

        # XADD в Redis (если подключены)
        if self._redis is not None:
            await self._redis.xadd(stream_key, data, maxlen=self._max_len)

            # Убедиться что consumer group существует для этого stream (idempotent)
            try:
                await self._redis.xgroup_create(
                    stream_key, CONSUMER_GROUP, id="0", mkstream=True
                )
            except Exception as e:
                # BUSYGROUP is expected if group already exists — suppress
                if "BUSYGROUP" not in str(e):
                    logger.debug("xgroup_create for %s: %s", stream_key, e)

        # Локальная доставка (in-process подписчики)
        await self._dispatch_local(event_type, event_id, payload)

    def subscribe(
        self,
        event_type: str,
        handler: AnyEventHandler,
        *,
        priority: int = 0,
    ) -> None:
        """Подписаться на тип события (локальный handler)."""
        _ = priority
        event_type = str(event_type) if event_type else "*"
        self._subscribers.setdefault(event_type, []).append(handler)

    def unsubscribe(self, event_type: str, handler: AnyEventHandler) -> None:
        event_type = str(event_type) if event_type else "*"
        handlers = self._subscribers.get(event_type, [])
        try:
            handlers.remove(handler)
        except ValueError:
            pass

    async def claim_event(self, event_id: str, worker_id: str) -> bool:
        """Для совместимости с IEventBus. В Redis Streams claim = XREADGROUP."""
        _ = (event_id, worker_id)
        return True

    async def add_middleware(self, middleware: Any) -> None:
        async with self._lock:
            self._middleware.append(middleware)

    async def remove_middleware(self, middleware: Any) -> None:
        async with self._lock:
            try:
                self._middleware.remove(middleware)
            except ValueError:
                pass

    async def list_middleware(self) -> list[str]:
        async with self._lock:
            return [getattr(mw, "__class__", type(mw)).__name__ for mw in self._middleware]

    async def get_unprocessed_events(self) -> list[dict[str, Any]]:
        """Получить summary по pending entry list (best-effort)."""
        if self._redis is None:
            return []

        result: list[dict[str, Any]] = []
        # Для каждого известного stream — XPENDING summary
        for event_type in list(self._subscribers.keys()):
            stream_key = f"{STREAM_PREFIX}{event_type}"
            try:
                pending = await self._redis.xpending(stream_key, CONSUMER_GROUP)
                if pending and pending.get("pending"):
                    result.append({"stream": stream_key, **pending})
            except Exception:
                pass
        return result

    async def is_event_processed(self, event_id: str) -> bool:
        return str(event_id) in self._processed_events

    async def mark_event_processed(self, event_id: str) -> None:
        self._processed_events.add(str(event_id))

    # ─── Internal ───────────────────────────────────────────────────

    async def _invoke_handler(
        self, handler: AnyEventHandler, event_type: str, payload: dict[str, Any]
    ) -> None:
        if inspect.iscoroutinefunction(handler):
            await handler(event_type, payload)
            return
        out = handler(event_type, payload)
        if inspect.isawaitable(out):
            await out

    async def _dispatch_local(
        self,
        event_type: str,
        event_id: str,
        payload: dict[str, Any],
    ) -> None:
        handlers = list(self._subscribers.get(event_type, [])) + list(
            self._subscribers.get("*", [])
        )

        async with self._lock:
            middleware = list(self._middleware)

        for mw in middleware:
            before = getattr(mw, "before_publish", None)
            if callable(before):
                await before(event_type, payload)

        if handlers:

            async def run_with_backpressure(handler: AnyEventHandler) -> None:
                async with self._handler_semaphore:
                    await self._invoke_handler(handler, event_type, payload)

            results = await asyncio.gather(
                *[run_with_backpressure(handler) for handler in handlers],
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, Exception):
                    logger.error(
                        "[RedisEventBus] Handler error for '%s': %s",
                        event_type,
                        result,
                    )
                    for mw in middleware:
                        on_err = getattr(mw, "on_handler_error", None)
                        if callable(on_err):
                            try:
                                await on_err(event_type, payload, result)
                            except Exception:
                                pass

        for mw in middleware:
            after = getattr(mw, "after_publish", None)
            if callable(after):
                await after(event_type, payload, len(handlers))

        await self.mark_event_processed(event_id)

    async def _reader_loop(self) -> None:
        """Фоновый reader: XREADGROUP для событий из других процессов."""
        if self._redis is None:
            return

        logger.info("[RedisEventBus] Reader loop started")
        while self._running:
            try:
                # Читаем только stream'ы по которым есть локальные подписки.
                # Это v1 компромисс: автоматического discovery всех event_type нет.
                streams = {
                    f"{STREAM_PREFIX}{event_type}": ">"
                    for event_type in list(self._subscribers.keys())
                    if event_type and event_type != "*"
                }
                if not streams:
                    await asyncio.sleep(1)
                    continue

                results = await self._redis.xreadgroup(
                    groupname=CONSUMER_GROUP,
                    consumername=self._consumer_name,
                    streams=streams,
                    count=self._batch_size,
                    block=self._block_ms,
                )
                if not results:
                    continue

                for stream_key, messages in results:
                    event_type = str(stream_key).removeprefix(STREAM_PREFIX)
                    for msg_id, fields in messages:
                        event_id = str(fields.get("event_id") or msg_id)
                        # Пропустить события которые мы уже доставили локально (publish)
                        if await self.is_event_processed(event_id):
                            try:
                                await self._redis.xack(stream_key, CONSUMER_GROUP, msg_id)
                            except Exception:
                                pass
                            continue

                        try:
                            payload_raw = fields.get("payload", "{}")
                            payload = json.loads(payload_raw) if payload_raw else {}
                            if not isinstance(payload, dict):
                                payload = {}
                            await self._dispatch_local(event_type, event_id, payload)
                            await self._redis.xack(stream_key, CONSUMER_GROUP, msg_id)
                        except Exception as exc:
                            logger.error(
                                "[RedisEventBus] Failed to process message %s: %s",
                                msg_id,
                                exc,
                            )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("[RedisEventBus] Reader loop error: %s", exc)
                await asyncio.sleep(1)

        logger.info("[RedisEventBus] Reader loop stopped")

