import asyncio
import pytest

from core.state_engine import StateEngine


@pytest.mark.asyncio
async def test_set_get_delete_exists_keys_clear_update():
    s = StateEngine()

    await s.set('k1', 1)
    assert await s.get('k1') == 1
    assert await s.exists('k1') is True

    await s.set('k2', 'v')
    keys = await s.keys()
    assert 'k1' in keys and 'k2' in keys

    removed = await s.delete('k1')
    assert removed is True
    assert await s.exists('k1') is False

    await s.update({'a': 10, 'b': 20})
    assert await s.get('a') == 10

    await s.clear()
    assert (await s.keys()) == []


@pytest.mark.asyncio
async def test_concurrent_set():
    s = StateEngine()

    async def set_n(n):
        await s.set(f'k{n}', n)

    await asyncio.gather(*(set_n(i) for i in range(50)))
    keys = await s.keys()
    assert len(keys) == 50
