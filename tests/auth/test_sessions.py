"""
Тесты для modules/api/auth/sessions.py
"""
import pytest
import time
from unittest.mock import AsyncMock, MagicMock
from modules.api.auth import (
    validate_session,
    create_session,
    delete_session,
    list_sessions,
    revoke_all_sessions,
    extract_session_from_cookie
)
from modules.api.auth.constants import AUTH_SESSIONS_NAMESPACE, DEFAULT_SESSION_EXPIRATION_SECONDS
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
    request.cookies = {}
    return request


class TestValidateSession:
    """Тесты для validate_session()."""
    
    @pytest.mark.asyncio
    async def test_valid_session_returns_context(self, mock_runtime):
        """Тест: валидная сессия возвращает RequestContext."""
        session_id = "session_123"
        session_data = {
            "user_id": "user_test",
            "scopes": ["devices.read", "devices.write"],
            "is_admin": False,
            "created_at": time.time(),
            "expires_at": time.time() + 3600
        }
        
        mock_runtime.storage.get.return_value = session_data
        
        context = await validate_session(mock_runtime, session_id)
        
        assert context is not None
        assert isinstance(context, RequestContext)
        assert context.user_id == "user_test"
        assert "devices.read" in context.scopes
        assert context.is_admin is False
        assert context.source == "session"
        assert context.session_id == session_id
    
    @pytest.mark.asyncio
    async def test_nonexistent_session_returns_none(self, mock_runtime):
        """Тест: несуществующая сессия возвращает None."""
        mock_runtime.storage.get.return_value = None
        
        context = await validate_session(mock_runtime, "invalid_session")
        
        assert context is None
    
    @pytest.mark.asyncio
    async def test_expired_session_returns_none(self, mock_runtime):
        """Тест: истекшая сессия возвращает None и удаляется."""
        session_id = "expired_session"
        session_data = {
            "user_id": "user_test",
            "scopes": ["devices.read"],
            "is_admin": False,
            "created_at": time.time() - 7200,
            "expires_at": time.time() - 3600  # Истекла час назад
        }
        
        mock_runtime.storage.get.return_value = session_data
        mock_runtime.storage.delete.return_value = True
        
        context = await validate_session(mock_runtime, session_id)
        
        assert context is None
        mock_runtime.storage.delete.assert_called()
    
    @pytest.mark.asyncio
    async def test_revoked_session_returns_none(self, mock_runtime):
        """Тест: отозванная сессия возвращает None."""
        session_id = "revoked_session"
        
        # Mock is_revoked
        async def mock_is_revoked(runtime, identifier, id_type):
            return True
        
        import modules.api.auth.sessions as sessions_module
        original_is_revoked = sessions_module.is_revoked
        sessions_module.is_revoked = mock_is_revoked
        
        try:
            context = await validate_session(mock_runtime, session_id)
            assert context is None
        finally:
            sessions_module.is_revoked = original_is_revoked


class TestCreateSession:
    """Тесты для create_session()."""
    
    @pytest.mark.asyncio
    async def test_create_session_success(self, mock_runtime):
        """Тест: успешное создание сессии."""
        user_id = "user_test"
        scopes = ["devices.read", "devices.write"]
        
        mock_runtime.storage.set.return_value = None
        
        session_id = await create_session(
            mock_runtime,
            user_id=user_id,
            scopes=scopes,
            is_admin=False
        )
        
        assert session_id is not None
        assert len(session_id) >= 32
        
        # Verify storage.set was called
        mock_runtime.storage.set.assert_called_once()
        call_args = mock_runtime.storage.set.call_args
        assert call_args[0][0] == AUTH_SESSIONS_NAMESPACE
        assert call_args[0][1] == session_id
        
        session_data = call_args[0][2]
        assert session_data["user_id"] == user_id
        assert session_data["scopes"] == scopes
        assert session_data["is_admin"] is False
        assert "created_at" in session_data
        assert "expires_at" in session_data
    
    @pytest.mark.asyncio
    async def test_create_session_with_custom_expiration(self, mock_runtime):
        """Тест: создание сессии с custom expiration."""
        user_id = "user_test"
        scopes = ["devices.read"]
        expires_in = 7200  # 2 часа
        
        mock_runtime.storage.set.return_value = None
        
        session_id = await create_session(
            mock_runtime,
            user_id=user_id,
            scopes=scopes,
            is_admin=False,
            expires_in=expires_in
        )
        
        call_args = mock_runtime.storage.set.call_args
        session_data = call_args[0][2]
        
        # Check expiration
        expected_expiration = time.time() + expires_in
        assert abs(session_data["expires_at"] - expected_expiration) < 5


class TestDeleteSession:
    """Тесты для delete_session()."""
    
    @pytest.mark.asyncio
    async def test_delete_session_success(self, mock_runtime):
        """Тест: успешное удаление сессии."""
        session_id = "session_to_delete"
        
        mock_runtime.storage.delete.return_value = True
        
        result = await delete_session(mock_runtime, session_id)
        
        assert result is True
        mock_runtime.storage.delete.assert_called_once_with(
            AUTH_SESSIONS_NAMESPACE,
            session_id
        )
    
    @pytest.mark.asyncio
    async def test_delete_nonexistent_session(self, mock_runtime):
        """Тест: удаление несуществующей сессии."""
        mock_runtime.storage.delete.return_value = False
        
        result = await delete_session(mock_runtime, "nonexistent")
        
        assert result is False


class TestListSessions:
    """Тесты для list_sessions()."""
    
    @pytest.mark.asyncio
    async def test_list_sessions_for_user(self, mock_runtime):
        """Тест: список сессий пользователя."""
        user_id = "user_test"
        
        all_keys = ["session_1", "session_2", "session_3"]
        mock_runtime.storage.list_keys.return_value = all_keys
        
        # Mock get для каждой сессии
        sessions_data = {
            "session_1": {"user_id": "user_test", "created_at": time.time()},
            "session_2": {"user_id": "other_user", "created_at": time.time()},
            "session_3": {"user_id": "user_test", "created_at": time.time()}
        }
        
        async def mock_get(namespace, key):
            return sessions_data.get(key)
        
        mock_runtime.storage.get.side_effect = mock_get
        
        sessions = await list_sessions(mock_runtime, user_id)
        
        assert len(sessions) == 2
        assert all(s["user_id"] == user_id for s in sessions)


class TestRevokeAllSessions:
    """Тесты для revoke_all_sessions()."""
    
    @pytest.mark.asyncio
    async def test_revoke_all_sessions_for_user(self, mock_runtime):
        """Тест: отзыв всех сессий пользователя."""
        user_id = "user_test"
        
        # Mock list_sessions
        sessions = [
            {"session_id": "session_1", "user_id": user_id},
            {"session_id": "session_2", "user_id": user_id}
        ]
        
        import modules.api.auth.sessions as sessions_module
        original_list = sessions_module.list_sessions
        
        async def mock_list_sessions(runtime, uid):
            return sessions
        
        sessions_module.list_sessions = mock_list_sessions
        
        mock_runtime.storage.delete.return_value = True
        
        try:
            count = await revoke_all_sessions(mock_runtime, user_id)
            
            assert count == 2
            assert mock_runtime.storage.delete.call_count == 2
        finally:
            sessions_module.list_sessions = original_list


class TestExtractSessionFromCookie:
    """Тесты для extract_session_from_cookie()."""
    
    def test_extract_session_from_cookie(self, mock_request):
        """Тест: извлечение session из cookie."""
        mock_request.cookies = {"session_id": "test_session_123"}
        
        session_id = extract_session_from_cookie(mock_request)
        
        assert session_id == "test_session_123"
    
    def test_no_cookie_returns_none(self, mock_request):
        """Тест: отсутствие cookie возвращает None."""
        mock_request.cookies = {}
        
        session_id = extract_session_from_cookie(mock_request)
        
        assert session_id is None
    
    def test_empty_cookie_returns_none(self, mock_request):
        """Тест: пустой cookie возвращает None."""
        mock_request.cookies = {"session_id": ""}
        
        session_id = extract_session_from_cookie(mock_request)
        
        assert session_id is None
