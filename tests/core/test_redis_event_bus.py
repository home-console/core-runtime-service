"""Тесты RedisStreamsEventBus без реального Redis (pure unit)."""

import pytest

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

