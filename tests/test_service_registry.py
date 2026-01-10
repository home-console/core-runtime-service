import pytest

from core.service_registry import ServiceRegistry


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
