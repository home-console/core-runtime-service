import pytest

from core.storage import Storage


@pytest.mark.asyncio
async def test_storage_crud(memory_adapter):
    storage = Storage(memory_adapter)

    await storage.set('ns', 'k1', {'v': 1})
    got = await storage.get('ns', 'k1')
    assert got == {'v': 1}

    keys = await storage.list_keys('ns')
    assert 'k1' in keys

    deleted = await storage.delete('ns', 'k1')
    assert deleted is True

    await storage.set('ns', 'k2', {'v': 2})
    await storage.clear_namespace('ns')
    keys = await storage.list_keys('ns')
    assert keys == []

    await storage.close()
    assert memory_adapter.closed is True
