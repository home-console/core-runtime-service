import pytest

from core.service.models import ServiceMiddleware
from core.service.registry import ServiceRegistry


@pytest.mark.asyncio
async def test_register_and_call():
    sr = ServiceRegistry()

    async def srv(a, b=0):
        return a + b

    await sr.register('sum', srv)
    assert await sr.has_service('sum')
    assert 'sum' in await sr.list_services()

    res = await sr.call('sum', 2, b=3)
    assert res == 5


@pytest.mark.asyncio
async def test_register_duplicate_raises():
    sr = ServiceRegistry()

    async def f():
        pass

    await sr.register('s', f)
    with pytest.raises(ValueError):
        await sr.register('s', f)


@pytest.mark.asyncio
async def test_call_missing_raises():
    sr = ServiceRegistry()
    with pytest.raises(ValueError):
        await sr.call('nope')


@pytest.mark.asyncio
async def test_unregister_and_clear():
    sr = ServiceRegistry()

    async def f():
        pass

    await sr.register('t', f)
    await sr.unregister('t')
    assert not await sr.has_service('t')
    await sr.register('a', f)
    await sr.clear()
    assert await sr.list_services() == []


class _TrackingMiddleware(ServiceMiddleware):
    def __init__(self):
        self.events = []

    async def before_call(self, service_name: str, args: tuple, kwargs: dict) -> None:
        self.events.append(("before", service_name))

    async def after_call(self, service_name: str, result):
        self.events.append(("after", service_name, result))

    async def on_error(self, service_name: str, error: Exception) -> None:
        self.events.append(("error", service_name, type(error).__name__))


@pytest.mark.asyncio
async def test_global_middleware_applied_to_call():
    sr = ServiceRegistry()
    mw = _TrackingMiddleware()

    async def srv():
        return "ok"

    await sr.add_middleware(mw)
    await sr.register("test", srv)

    assert await sr.call("test") == "ok"
    assert mw.events == [("before", "test"), ("after", "test", "ok")]
    assert " _TrackingMiddleware".strip() in await sr.list_middleware()


@pytest.mark.asyncio
async def test_global_middleware_receives_errors():
    sr = ServiceRegistry()
    mw = _TrackingMiddleware()

    async def srv():
        raise RuntimeError("boom")

    await sr.add_middleware(mw)
    await sr.register("test", srv)

    with pytest.raises(RuntimeError):
        await sr.call("test")

    assert ("before", "test") in mw.events
    assert ("error", "test", "RuntimeError") in mw.events
