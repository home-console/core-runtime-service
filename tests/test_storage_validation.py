"""
Тесты для валидации Storage API.

Проверяют, что Storage корректно валидирует входные данные.
"""

import pytest

from core.storage import Storage


@pytest.mark.asyncio
async def test_set_validates_dict_type(memory_adapter):
    """Проверка, что set() требует dict."""
    storage = Storage(memory_adapter)
    
    # Должно работать с dict
    await storage.set("test", "key", {"value": 1})
    assert await storage.get("test", "key") == {"value": 1}
    
    # Должно падать со строкой
    with pytest.raises(TypeError, match="value must be dict"):
        await storage.set("test", "key", "not a dict")
    
    # Должно падать с числом
    with pytest.raises(TypeError, match="value must be dict"):
        await storage.set("test", "key", 123)
    
    # Должно падать со списком
    with pytest.raises(TypeError, match="value must be dict"):
        await storage.set("test", "key", [1, 2, 3])
    
    # Должно падать с None
    with pytest.raises(TypeError, match="value must be dict"):
        await storage.set("test", "key", None)


@pytest.mark.asyncio
async def test_set_validates_namespace(memory_adapter):
    """Проверка валидации namespace."""
    storage = Storage(memory_adapter)
    
    # Должно работать с валидным namespace
    await storage.set("valid_namespace", "key", {"value": 1})
    
    # Должно падать с пустой строкой
    with pytest.raises(ValueError, match="namespace must be non-empty string"):
        await storage.set("", "key", {"value": 1})
    
    # Должно падать с None
    with pytest.raises(ValueError, match="namespace must be non-empty string"):
        await storage.set(None, "key", {"value": 1})
    
    # Должно падать с числом
    with pytest.raises(ValueError, match="namespace must be non-empty string"):
        await storage.set(123, "key", {"value": 1})


@pytest.mark.asyncio
async def test_set_validates_key(memory_adapter):
    """Проверка валидации key."""
    storage = Storage(memory_adapter)
    
    # Должно работать с валидным key
    await storage.set("test", "valid_key", {"value": 1})
    
    # Должно падать с пустой строкой
    with pytest.raises(ValueError, match="key must be non-empty string"):
        await storage.set("test", "", {"value": 1})
    
    # Должно падать с None
    with pytest.raises(ValueError, match="key must be non-empty string"):
        await storage.set("test", None, {"value": 1})
    
    # Должно падать с числом
    with pytest.raises(ValueError, match="key must be non-empty string"):
        await storage.set("test", 123, {"value": 1})


@pytest.mark.asyncio
async def test_get_validates_namespace_and_key(memory_adapter):
    """Проверка валидации namespace и key в get()."""
    storage = Storage(memory_adapter)
    
    # Должно работать с валидными параметрами
    await storage.set("test", "key", {"value": 1})
    result = await storage.get("test", "key")
    assert result == {"value": 1}
    
    # Должно падать с пустым namespace
    with pytest.raises(ValueError, match="namespace must be non-empty string"):
        await storage.get("", "key")
    
    # Должно падать с пустым key
    with pytest.raises(ValueError, match="key must be non-empty string"):
        await storage.get("test", "")


@pytest.mark.asyncio
async def test_delete_validates_namespace_and_key(memory_adapter):
    """Проверка валидации namespace и key в delete()."""
    storage = Storage(memory_adapter)
    
    # Должно работать с валидными параметрами
    await storage.set("test", "key", {"value": 1})
    deleted = await storage.delete("test", "key")
    assert deleted is True
    
    # Должно падать с пустым namespace
    with pytest.raises(ValueError, match="namespace must be non-empty string"):
        await storage.delete("", "key")
    
    # Должно падать с пустым key
    with pytest.raises(ValueError, match="key must be non-empty string"):
        await storage.delete("test", "")


@pytest.mark.asyncio
async def test_list_keys_validates_namespace(memory_adapter):
    """Проверка валидации namespace в list_keys()."""
    storage = Storage(memory_adapter)
    
    # Должно работать с валидным namespace
    await storage.set("test", "key1", {"value": 1})
    keys = await storage.list_keys("test")
    assert "key1" in keys
    
    # Должно падать с пустым namespace
    with pytest.raises(ValueError, match="namespace must be non-empty string"):
        await storage.list_keys("")
    
    # Должно падать с None
    with pytest.raises(ValueError, match="namespace must be non-empty string"):
        await storage.list_keys(None)


@pytest.mark.asyncio
async def test_storage_mirror_validates_types(memory_adapter):
    """Проверка, что StorageWithStateMirror также валидирует типы."""
    from core.storage_mirror import StorageWithStateMirror
    from core.state_engine import StateEngine
    
    storage = Storage(memory_adapter)
    state_engine = StateEngine()
    storage_mirror = StorageWithStateMirror(storage, state_engine)
    
    # Должно работать с dict
    await storage_mirror.set("test", "key", {"value": 1})
    assert await storage_mirror.get("test", "key") == {"value": 1}
    
    # Должно падать со строкой (валидация из Storage.set)
    with pytest.raises(TypeError, match="value must be dict"):
        await storage_mirror.set("test", "key", "not a dict")
    
    # Должно падать с пустым namespace
    with pytest.raises(ValueError, match="namespace must be non-empty string"):
        await storage_mirror.set("", "key", {"value": 1})
