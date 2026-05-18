"""Тесты RedisStreamsEventBus без реального Redis (pure unit)."""

import pytest

from core.messaging import EventBusMiddleware, resolve_max_concurrent_handlers
from core.messaging_redis import RedisStreamsEventBus
from core.ports import IEventBus


def test_redis_event_bus_implements_interface():
    """RedisStreamsEventBus должен соответствовать IEventBus."""
    bus = RedisStreamsEventBus(redis_url="redis://localhost:6379")
    assert isinstance(bus, IEventBus)


@pytest.mark.asyncio
async def test_publish_dispatches_locally_without_redis():
    """Локальная доставка работает даже без Redis (redis не подключен)."""
    bus = RedisStreamsEventBus()
    received: list[dict] = []
    bus.subscribe("test.event", lambda _et, payload: received.append(payload))
    await bus.publish("test.event", {"key": "value"})
    assert received == [{"key": "value"}]


@pytest.mark.asyncio
async def test_subscribe_unsubscribe():
    bus = RedisStreamsEventBus()
    calls: list[dict] = []

    async def handler(_et, payload):
        calls.append(payload)

    bus.subscribe("foo", handler)
    await bus.publish("foo", {"x": 1})
    assert calls == [{"x": 1}]

    bus.unsubscribe("foo", handler)
    await bus.publish("foo", {"x": 2})
    assert calls == [{"x": 1}]


@pytest.mark.asyncio
async def test_factory_returns_inmemory_by_default(monkeypatch):
    monkeypatch.delenv("EVENT_BUS_BACKEND", raising=False)
    from core.messaging_factory import create_event_bus
    from core.messaging import InMemoryEventBus

    bus = create_event_bus()
    assert isinstance(bus, InMemoryEventBus)


@pytest.mark.asyncio
async def test_factory_returns_redis_when_configured(monkeypatch):
    monkeypatch.setenv("EVENT_BUS_BACKEND", "redis")
    from core.messaging_factory import create_event_bus

    bus = create_event_bus()
    assert isinstance(bus, RedisStreamsEventBus)


def test_resolve_max_concurrent_handlers_from_env(monkeypatch):
    monkeypatch.setenv("EVENT_BUS_MAX_CONCURRENT_HANDLERS", "42")
    assert resolve_max_concurrent_handlers() == 42
    assert resolve_max_concurrent_handlers(7) == 7


def test_resolve_max_concurrent_handlers_invalid_env_falls_back(monkeypatch):
    monkeypatch.setenv("EVENT_BUS_MAX_CONCURRENT_HANDLERS", "not-a-number")
    assert resolve_max_concurrent_handlers() == 100


@pytest.mark.asyncio
async def test_factory_passes_max_concurrent_handlers(monkeypatch):
    monkeypatch.setenv("EVENT_BUS_MAX_CONCURRENT_HANDLERS", "25")
    from core.messaging_factory import create_event_bus
    from core.messaging import InMemoryEventBus

    bus = create_event_bus()
    assert isinstance(bus, InMemoryEventBus)
    assert bus._handler_semaphore._value == 25


class _TrackingRedisMiddleware(EventBusMiddleware):
    def __init__(self):
        self.events: list[tuple] = []

    async def before_publish(self, event_type, data):
        self.events.append(("before", event_type, data))

    async def after_publish(self, event_type, data, subscriber_count):
        self.events.append(("after", event_type, subscriber_count))

    async def on_handler_error(self, event_type, data, error):
        self.events.append(("error", event_type, type(error).__name__))


@pytest.mark.asyncio
async def test_redis_middleware_full_publish_lifecycle():
    bus = RedisStreamsEventBus()
    mw = _TrackingRedisMiddleware()
    await bus.add_middleware(mw)

    async def handler(_et, _payload):
        return None

    bus.subscribe("evt", handler)
    await bus.publish("evt", {"v": 1})

    before = [e for e in mw.events if e[0] == "before" and e[1] == "evt"]
    assert len(before) == 1
    assert before[0][2]["v"] == 1
    assert ("after", "evt", 1) in mw.events


@pytest.mark.asyncio
async def test_redis_middleware_receives_handler_errors():
    bus = RedisStreamsEventBus()
    mw = _TrackingRedisMiddleware()
    await bus.add_middleware(mw)

    async def bad_handler(_et, _payload):
        raise ValueError("boom")

    bus.subscribe("evt", bad_handler)
    await bus.publish("evt", {"v": 1})

    assert ("error", "evt", "ValueError") in mw.events

