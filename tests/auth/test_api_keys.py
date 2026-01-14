"""
Тесты для modules/api/auth/api_keys.py
"""
import pytest
import time
from unittest.mock import AsyncMock, MagicMock
from modules.api.auth import validate_api_key, create_api_key, rotate_api_key, extract_api_key_from_header
from modules.api.auth.constants import AUTH_API_KEYS_NAMESPACE
from modules.api.auth.context import RequestContext
from fastapi import Request


@pytest.fixture
def mock_runtime():
    """Mock CoreRuntime для изоляции тестов."""
    runtime = MagicMock()
    runtime.storage = AsyncMock()
    runtime.service_registry = AsyncMock()
    return runtime


@pytest.fixture
def mock_request():
    """Mock FastAPI Request."""
    request = MagicMock(spec=Request)
    request.headers = {}
    return request


class TestValidateApiKey:
    """Тесты для validate_api_key()."""
    
    @pytest.mark.asyncio
    async def test_valid_api_key_returns_context(self, mock_runtime):
        """Тест: валидный API key возвращает RequestContext."""
        # Arrange
        api_key = "test_key_123"
        key_data = {
            "subject": "user:test",
            "scopes": ["devices.read"],
            "is_admin": False,
            "expires_at": None
        }
        mock_runtime.storage.get.return_value = key_data
        
        # Act
        context = await validate_api_key(mock_runtime, api_key)
        
        # Assert
        assert context is not None
        assert isinstance(context, RequestContext)
        assert context.subject == "user:test"
        assert "devices.read" in context.scopes
        assert context.is_admin is False
        assert context.source == "api_key"
        
        # Verify storage was called (может быть вызвано несколько раз из-за is_revoked)
        assert mock_runtime.storage.get.called
        # Проверяем что был вызов с правильными параметрами
        calls = [call for call in mock_runtime.storage.get.call_args_list 
                 if call[0][0] == AUTH_API_KEYS_NAMESPACE]
        assert len(calls) > 0
    
    @pytest.mark.asyncio
    async def test_nonexistent_key_returns_none(self, mock_runtime):
        """Тест: несуществующий ключ возвращает None."""
        mock_runtime.storage.get.return_value = None
        
        context = await validate_api_key(mock_runtime, "invalid_key")
        
        assert context is None
    
    @pytest.mark.asyncio
    async def test_empty_key_returns_none(self, mock_runtime):
        """Тест: пустой ключ возвращает None."""
        context = await validate_api_key(mock_runtime, "")
        assert context is None
        
        context = await validate_api_key(mock_runtime, "   ")
        assert context is None
    
    @pytest.mark.asyncio
    async def test_expired_key_returns_none(self, mock_runtime):
        """Тест: истекший ключ возвращает None и удаляется."""
        api_key = "expired_key"
        key_data = {
            "subject": "user:test",
            "scopes": ["devices.read"],
            "is_admin": False,
            "expires_at": time.time() - 3600  # Истёк час назад
        }
        mock_runtime.storage.get.return_value = key_data
        mock_runtime.storage.delete.return_value = True
        
        context = await validate_api_key(mock_runtime, api_key)
        
        assert context is None
        # Verify key was deleted
        mock_runtime.storage.delete.assert_called()
    
    @pytest.mark.asyncio
    async def test_revoked_key_returns_none(self, mock_runtime):
        """Тест: отозванный ключ возвращает None."""
        api_key = "revoked_key"
        
        # Mock is_revoked to return True
        async def mock_is_revoked(runtime, identifier, id_type):
            return True
        
        # Patch is_revoked in the module
        import modules.api.auth.api_keys as api_keys_module
        original_is_revoked = api_keys_module.is_revoked
        api_keys_module.is_revoked = mock_is_revoked
        
        try:
            context = await validate_api_key(mock_runtime, api_key)
            assert context is None
        finally:
            api_keys_module.is_revoked = original_is_revoked
    
    @pytest.mark.asyncio
    async def test_invalid_data_structure_returns_none(self, mock_runtime):
        """Тест: невалидная структура данных возвращает None."""
        mock_runtime.storage.get.return_value = "not a dict"
        
        context = await validate_api_key(mock_runtime, "test_key")
        
        assert context is None


class TestCreateApiKey:
    """Тесты для create_api_key()."""
    
    @pytest.mark.asyncio
    async def test_create_api_key_success(self, mock_runtime):
        """Тест: успешное создание API key."""
        # Arrange
        subject = "user:test"
        scopes = ["devices.read", "devices.write"]
        mock_runtime.storage.set.return_value = None
        
        # Act
        api_key = await create_api_key(
            mock_runtime,
            subject=subject,
            scopes=scopes,
            is_admin=False
        )
        
        # Assert
        assert api_key is not None
        assert len(api_key) >= 32  # Minimum length for security
        
        # Verify storage.set was called (может быть несколько раз - ключ + audit)
        assert mock_runtime.storage.set.called
        # Найдем вызов для создания ключа
        api_key_calls = [call for call in mock_runtime.storage.set.call_args_list 
                         if call[0][0] == AUTH_API_KEYS_NAMESPACE]
        assert len(api_key_calls) > 0
        
        call_args = api_key_calls[0]
        assert call_args[0][1] == api_key
        
        key_data = call_args[0][2]
        assert key_data["subject"] == subject
        assert key_data["scopes"] == scopes
    
    @pytest.mark.asyncio
    async def test_create_api_key_with_expiration(self, mock_runtime):
        """Тест: создание ключа с expiration."""
        subject = "user:test"
        scopes = ["devices.read"]
        expires_in = 3600  # 1 час
        
        mock_runtime.storage.set.return_value = None
        
        # expires_at вместо expires_in
        expires_at = time.time() + expires_in
        
        api_key = await create_api_key(
            mock_runtime,
            subject=subject,
            scopes=scopes,
            expires_at=expires_at
        )
        
        assert api_key is not None
        
        # Check expires_at is set
        api_key_calls = [call for call in mock_runtime.storage.set.call_args_list 
                         if call[0][0] == AUTH_API_KEYS_NAMESPACE]
        key_data = api_key_calls[0][0][2]
        assert "expires_at" in key_data
        assert key_data["expires_at"] == expires_at
    
    @pytest.mark.asyncio
    async def test_create_admin_key(self, mock_runtime):
        """Тест: создание admin ключа."""
        subject = "admin:root"
        scopes = ["*"]
        
        mock_runtime.storage.set.return_value = None
        
        api_key = await create_api_key(
            mock_runtime,
            subject=subject,
            scopes=scopes
        )
        
        # Проверяем что ключ создан (is_admin определяется по subject)
        assert api_key is not None
        api_key_calls = [call for call in mock_runtime.storage.set.call_args_list 
                         if call[0][0] == AUTH_API_KEYS_NAMESPACE]
        assert len(api_key_calls) > 0


class TestRotateApiKey:
    """Тесты для rotate_api_key()."""
    
    @pytest.mark.asyncio
    async def test_rotate_api_key_success(self, mock_runtime):
        """Тест: успешная ротация ключа."""
        old_key = "old_key_123"
        old_data = {
            "subject": "user:test",
            "scopes": ["devices.read"],
            "is_admin": False,
            "expires_at": None
        }
        
        mock_runtime.storage.get.return_value = old_data
        mock_runtime.storage.set.return_value = None
        mock_runtime.storage.delete.return_value = True
        
        new_key = await rotate_api_key(mock_runtime, old_key)
        
        assert new_key is not None
        assert new_key != old_key
        assert len(new_key) >= 32
        
        # Verify old key was deleted
        mock_runtime.storage.delete.assert_called_with(AUTH_API_KEYS_NAMESPACE, old_key)
    
    @pytest.mark.asyncio
    async def test_rotate_nonexistent_key_raises(self, mock_runtime):
        """Тест: ротация несуществующего ключа вызывает ValueError."""
        mock_runtime.storage.get.return_value = None
        
        with pytest.raises(ValueError, match="not found"):
            await rotate_api_key(mock_runtime, "nonexistent_key")


class TestExtractApiKeyFromHeader:
    """Тесты для extract_api_key_from_header()."""
    
    def test_extract_bearer_token(self, mock_request):
        """Тест: извлечение Bearer token."""
        mock_request.headers = {"Authorization": "Bearer test_key_123"}
        
        api_key = extract_api_key_from_header(mock_request)
        
        assert api_key == "test_key_123"
    
    def test_extract_without_bearer_prefix_returns_none(self, mock_request):
        """Тест: извлечение без Bearer prefix возвращает None."""
        mock_request.headers = {"Authorization": "test_key_123"}
        
        api_key = extract_api_key_from_header(mock_request)
        
        # Реализация требует Bearer prefix
        assert api_key is None
    
    def test_no_authorization_header_returns_none(self, mock_request):
        """Тест: отсутствие заголовка возвращает None."""
        mock_request.headers = {}
        
        api_key = extract_api_key_from_header(mock_request)
        
        assert api_key is None
    
    def test_empty_authorization_header_returns_none(self, mock_request):
        """Тест: пустой заголовок возвращает None."""
        mock_request.headers = {"Authorization": ""}
        
        api_key = extract_api_key_from_header(mock_request)
        
        assert api_key is None
    
    def test_bearer_without_token_returns_none(self, mock_request):
        """Тест: Bearer без токена возвращает None."""
        mock_request.headers = {"Authorization": "Bearer"}
        
        api_key = extract_api_key_from_header(mock_request)
        
        assert api_key is None
