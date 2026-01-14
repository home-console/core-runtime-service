"""
Тесты для modules/api/auth/sessions.py
"""
import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch
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
    runtime.service_registry = MagicMock()
    runtime.service_registry.call = AsyncMock()
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
        
        mock_runtime.storage.set.return_value = None
        
        with patch('modules.api.auth.sessions.validate_user_exists', new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = True
            
            session_id = await create_session(
                mock_runtime,
                user_id=user_id
            )
            
            assert session_id is not None
            assert len(session_id) >= 32
        
            # Verify storage.set was called (дважды - для сессии и для audit log)
            call_args_list = mock_runtime.storage.set.call_args_list
            assert len(call_args_list) >= 1
            
            # Первый вызов - сохранение сессии
            call_args = call_args_list[0]
            assert call_args[0][0] == AUTH_SESSIONS_NAMESPACE
            assert call_args[0][1] == session_id
            
            session_data = call_args[0][2]
            assert session_data["user_id"] == user_id
            assert "created_at" in session_data
            assert "expires_at" in session_data


class TestDeleteSession:
    """Тесты для delete_session()."""
    
    @pytest.mark.asyncio
    async def test_delete_session_success(self, mock_runtime):
        """Тест: успешное удаление сессии."""
        session_id = "session_to_delete"
        
        mock_runtime.storage.delete.return_value = True
        
        await delete_session(mock_runtime, session_id)
        
        mock_runtime.storage.delete.assert_called_once_with(
            AUTH_SESSIONS_NAMESPACE,
            session_id
        )
    
    @pytest.mark.asyncio
    async def test_delete_nonexistent_session(self, mock_runtime):
        """Тест: удаление несуществующей сессии."""
        mock_runtime.storage.delete.return_value = False
        
        await delete_session(mock_runtime, "nonexistent")


class TestListSessions:
    """Тесты для list_sessions()."""
    
    @pytest.mark.asyncio
    async def test_list_sessions_for_user(self, mock_runtime):
        """Тест: список сессий пользователя."""
        user_id = "user_test"
        current_time = time.time()

        all_keys = ["session_1", "session_2", "session_3"]

        sessions_data = {
            "session_1": {
                "user_id": "user_test",
                "created_at": current_time,
                "expires_at": current_time + 3600,
                "last_used": current_time,
            },
            "session_2": {
                "user_id": "other_user",
                "created_at": current_time,
                "expires_at": current_time + 3600,
                "last_used": current_time,
            },
            "session_3": {
                "user_id": "user_test",
                "created_at": current_time,
                "expires_at": current_time + 3600,
                "last_used": current_time,
            },
        }

        class DummyStorage:
            async def list_keys(self, namespace):
                return all_keys

            async def get(self, namespace, key):
                return sessions_data.get(key)

        class DummyServiceRegistry:
            async def call(self, *args, **kwargs):
                return None

        runtime = MagicMock()
        runtime.storage = DummyStorage()
        runtime.service_registry = DummyServiceRegistry()

        sessions = await list_sessions(runtime, user_id)

        assert len(sessions) == 2
        assert all(s["user_id"] == user_id for s in sessions)


class TestRevokeAllSessions:
    """Тесты для revoke_all_sessions()."""
    
    @pytest.mark.asyncio
    async def test_revoke_all_sessions_for_user(self, mock_runtime):
        """Тест: отзыв всех сессий пользователя."""
        user_id = "user_test"
        current_time = time.time()

        # Настраиваем list_keys и get для возврата двух сессий пользователя и одной чужой
        all_keys = ["session_1", "session_2", "session_3"]
        mock_runtime.storage.list_keys = AsyncMock(return_value=all_keys)

        sessions_data = {
            "session_1": {"user_id": user_id, "created_at": current_time, "expires_at": current_time + 3600},
            "session_2": {"user_id": user_id, "created_at": current_time, "expires_at": current_time + 3600},
            "session_3": {"user_id": "other", "created_at": current_time, "expires_at": current_time + 3600},
        }

        async def mock_get(namespace, key):
            return sessions_data.get(key)

        mock_runtime.storage.get = AsyncMock(side_effect=mock_get)

        # Патчим revoke_session, чтобы не ходить в реальный код
        with patch("modules.api.auth.sessions.revoke_session", new=AsyncMock()) as mock_revoke:
            count = await revoke_all_sessions(mock_runtime, user_id)
            assert count == 2
            assert mock_revoke.await_count == 2


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
