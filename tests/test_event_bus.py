import asyncio

import pytest

from core.event_bus import EventBus


@pytest.mark.asyncio
async def test_subscribe_and_publish():
    bus = EventBus()
    received = {}

    async def handler(event_type, data):
        received['type'] = event_type
        received['data'] = data

    bus.subscribe('test.event', handler)
    await bus.publish('test.event', {'x': 1})

    # allow tasks to run
    await asyncio.sleep(0)

    assert received['type'] == 'test.event'
    assert received['data'] == {'x': 1}


@pytest.mark.asyncio
async def test_unsubscribe():
    bus = EventBus()

    async def handler(event_type, data):
        raise RuntimeError('should not be called')

    bus.subscribe('a', handler)
    bus.unsubscribe('a', handler)
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

    bus.subscribe('e', bad)
    bus.subscribe('e', good)

    await bus.publish('e', {})
    await asyncio.sleep(0)
    assert called is True


def test_subscribers_count_and_clear():
    bus = EventBus()

    async def h(e, d):
        pass

    bus.subscribe('x', h)
    bus.subscribe('x', h)
    assert bus.get_subscribers_count('x') == 2
    bus.clear()
    assert bus.get_subscribers_count('x') == 0
