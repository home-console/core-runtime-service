import asyncio

import pytest

from core.messaging import InMemoryEventBus as EventBus, EventBusMiddleware


@pytest.mark.asyncio
async def test_subscribe_and_publish():
    bus = EventBus()
    received = {}

    async def handler(event_type, data):
        received['type'] = event_type
        received['data'] = data

    await bus.subscribe('test.event', handler)
    await bus.publish('test.event', {'x': 1})

    # allow tasks to run
    await asyncio.sleep(0)

    assert received['type'] == 'test.event'
    assert received['data']['x'] == 1
    # Typed handler now also receives unified payload metadata
    assert received['data']['type'] == 'test.event'
    assert 'id' in received['data']


@pytest.mark.asyncio
async def test_subscribe_simple_handler_gets_type_and_id():
    bus = EventBus()
    received = {}

    async def simple_handler(payload):
        received['payload'] = payload

    await bus.subscribe(simple_handler)
    await bus.publish('simple.event', {'x': 1})

    await asyncio.sleep(0)

    assert received['payload']['type'] == 'simple.event'
    assert received['payload']['x'] == 1
    assert 'id' in received['payload']


@pytest.mark.asyncio
async def test_subscribe_simple_handler_for_specific_event_type_and_unsubscribe():
    bus = EventBus()
    received = {"count": 0}

    async def simple_handler(payload):
        received["count"] += 1
        assert payload["type"] == "x"
        assert "id" in payload

    await bus.subscribe("x", simple_handler)
    await bus.publish("x", {"v": 1})
    await asyncio.sleep(0)
    assert received["count"] == 1

    # Unsubscribe by passing the original simple handler (not the wrapper).
    await bus.unsubscribe("x", simple_handler)
    await bus.publish("x", {"v": 2})
    await asyncio.sleep(0)
    assert received["count"] == 1


@pytest.mark.asyncio
async def test_unsubscribe():
    bus = EventBus()

    async def handler(event_type, data):
        raise RuntimeError('should not be called')

    await bus.subscribe('a', handler)
    await bus.unsubscribe('a', handler)
    await bus.publish('a', {})


@pytest.mark.asyncio
async def test_publish_handler_exception_ignored():
    bus = EventBus()
    called = False

    async def bad(event_type, data):
        raise ValueError('boom')

    async def good(event_type, data):
        nonlocal called
        called = True

    await bus.subscribe('e', bad)
    await bus.subscribe('e', good)

    await bus.publish('e', {})
    await asyncio.sleep(0)
    assert called is True


@pytest.mark.asyncio
async def test_subscribers_count_and_clear():
    bus = EventBus()

    async def h(e, d):
        pass

    await bus.subscribe('x', h)
    await bus.subscribe('x', h)
    assert await bus.get_subscribers_count('x') == 2
    await bus.clear()
    assert await bus.get_subscribers_count('x') == 0


class _TrackingEventMiddleware(EventBusMiddleware):
    def __init__(self):
        self.events = []

    async def before_publish(self, event_type, data):
        self.events.append(("before", event_type, data))

    async def after_publish(self, event_type, data, subscriber_count):
        self.events.append(("after", event_type, subscriber_count))

    async def on_handler_error(self, event_type, data, error):
        self.events.append(("error", event_type, type(error).__name__))


@pytest.mark.asyncio
async def test_event_bus_middleware_receives_publish_lifecycle():
    bus = EventBus()
    mw = _TrackingEventMiddleware()

    async def handler(event_type, data):
        return None

    await bus.add_middleware(mw)
    await bus.subscribe("evt", handler)
    await bus.publish("evt", {"v": 1})

    before = [e for e in mw.events if e[0] == "before" and e[1] == "evt"]
    assert len(before) == 1
    assert before[0][2]["v"] == 1
    assert "id" in before[0][2]
    assert ("after", "evt", 1) in mw.events
    assert " _TrackingEventMiddleware".strip() in await bus.list_middleware()


@pytest.mark.asyncio
async def test_event_bus_middleware_receives_handler_errors():
    bus = EventBus()
    mw = _TrackingEventMiddleware()

    async def bad_handler(event_type, data):
        raise ValueError("boom")

    await bus.add_middleware(mw)
    await bus.subscribe("evt", bad_handler)
    await bus.publish("evt", {"v": 1})

    assert ("error", "evt", "ValueError") in mw.events
