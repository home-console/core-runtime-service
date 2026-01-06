import pytest

from core.service_registry import ServiceRegistry


@pytest.mark.asyncio
async def test_register_and_call():
    sr = ServiceRegistry()

    async def srv(a, b=0):
        return a + b

    sr.register('sum', srv)
    assert sr.has_service('sum')
    assert 'sum' in sr.list_services()

    res = await sr.call('sum', 2, b=3)
    assert res == 5


def test_register_duplicate_raises():
    sr = ServiceRegistry()

    async def f():
        pass

    sr.register('s', f)
    with pytest.raises(ValueError):
        sr.register('s', f)


@pytest.mark.asyncio
async def test_call_missing_raises():
    sr = ServiceRegistry()
    with pytest.raises(ValueError):
        await sr.call('nope')


def test_unregister_and_clear():
    sr = ServiceRegistry()

    async def f():
        pass

    sr.register('t', f)
    sr.unregister('t')
    assert not sr.has_service('t')
    sr.register('a', f)
    sr.clear()
    assert sr.list_services() == []
