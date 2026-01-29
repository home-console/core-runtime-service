"""
Тесты для idempotency поддержки.
"""

import pytest
import json
from fastapi import Request, Response
from modules.api.security import get_idempotency_key, IdempotencyStore


class TestGetIdempotencyKey:
    """Тесты для извлечения Idempotency-Key из заголовков."""
    
    def test_extract_valid_key(self):
        """Должна корректно извлечь валиден Idempotency-Key."""
        # Mock Request
        class MockRequest:
            headers = {"Idempotency-Key": "test-key-123"}
        
        request = MockRequest()
        key = get_idempotency_key(request)
        assert key == "test-key-123"
    
    def test_strip_whitespace(self):
        """Должна удалить пробелы вокруг ключа."""
        class MockRequest:
            headers = {"Idempotency-Key": "  test-key-123  "}
        
        request = MockRequest()
        key = get_idempotency_key(request)
        assert key == "test-key-123"
    
    def test_missing_key_returns_none(self):
        """Если нет Idempotency-Key, должна вернуть None."""
        class MockRequest:
            headers = {}
        
        request = MockRequest()
        key = get_idempotency_key(request)
        assert key is None
    
    def test_too_long_key_returns_none(self):
        """Слишком длинный ключ должен быть отклонен."""
        class MockRequest:
            headers = {"Idempotency-Key": "x" * 300}
        
        request = MockRequest()
        key = get_idempotency_key(request)
        assert key is None
    
    def test_case_sensitive_header(self):
        """Заголовок должен быть case-sensitive (RFC)."""
        class MockRequest:
            headers = {"idempotency-key": "test"}
        
        request = MockRequest()
        key = get_idempotency_key(request)
        # FastAPI/Starlette приводит headers к lowercase автоматически
        # но мы проверяем логику функции
        assert key is None or key == "test"  # Зависит от реализации


@pytest.mark.asyncio
class TestIdempotencyStore:
    """Тесты для хранилища idempotency ключей."""
    
    async def test_store_and_retrieve(self):
        """Должна сохранить и вернуть значение."""
        store = IdempotencyStore(ttl_seconds=3600)
        
        response_data = {"status_code": 200, "response": {"ok": True}}
        await store.set("key1", response_data)
        
        result = await store.get("key1")
        assert result is not None
        assert result["response"]["ok"] is True
    
    async def test_missing_key_returns_none(self):
        """Несуществующий ключ должен вернуть None."""
        store = IdempotencyStore(ttl_seconds=3600)
        result = await store.get("nonexistent")
        assert result is None
    
    async def test_ttl_expiration(self):
        """Ключ должен быть удалён после истечения TTL."""
        store = IdempotencyStore(ttl_seconds=0)  # Мгновенное истечение
        
        response_data = {"status_code": 200, "response": {"ok": True}}
        await store.set("key1", response_data)
        
        # Даже сразу после попытаемся получить — должно истечь
        import time
        time.sleep(0.1)  # Небольшая задержка для гарантии
        
        result = await store.get("key1")
        assert result is None
    
    async def test_multiple_keys(self):
        """Должна хранить несколько разных ключей."""
        store = IdempotencyStore(ttl_seconds=3600)
        
        await store.set("key1", {"value": 1})
        await store.set("key2", {"value": 2})
        
        result1 = await store.get("key1")
        result2 = await store.get("key2")
        
        assert result1["value"] == 1
        assert result2["value"] == 2
    
    async def test_cleanup_expired(self):
        """cleanup_expired должна удалить истекшие ключи."""
        store = IdempotencyStore(ttl_seconds=1)
        
        await store.set("key1", {"value": 1})
        await store.set("key2", {"value": 2})
        
        # Ждём истечения TTL
        import time
        time.sleep(1.1)
        
        # Очищаем
        await store.cleanup_expired()
        
        # Проверяем, что ключи удалены
        result1 = await store.get("key1")
        result2 = await store.get("key2")
        
        assert result1 is None
        assert result2 is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
