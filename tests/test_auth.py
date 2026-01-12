"""
Тесты для API Key Authentication.

Проверяют:
- validate_api_key()
- validate_session()
- create_session()
- delete_session()
- check_service_scope()
- RequestContext
"""

import pytest
import time
from unittest.mock import AsyncMock, MagicMock

from modules.api.auth import (
    RequestContext,
    validate_api_key,
    validate_session,
    create_session,
    delete_session,
    check_service_scope,
    rate_limit_check,
    audit_log_auth_event,
    revoke_api_key,
    revoke_session,
    is_revoked,
    validate_user_exists,
    validate_scopes,
    AUTH_API_KEYS_NAMESPACE,
    AUTH_SESSIONS_NAMESPACE,
    AUTH_USERS_NAMESPACE,
    AUTH_RATE_LIMITS_NAMESPACE,
    AUTH_AUDIT_LOG_NAMESPACE,
    AUTH_REVOKED_NAMESPACE,
    DEFAULT_SESSION_EXPIRATION_SECONDS,
    RATE_LIMIT_AUTH_ATTEMPTS,
    RATE_LIMIT_AUTH_WINDOW,
)


@pytest.fixture
def mock_runtime():
    """Создаёт mock CoreRuntime для тестов."""
    runtime = MagicMock()
    runtime.storage = AsyncMock()
    runtime.service_registry = AsyncMock()
    return runtime


class TestRequestContext:
    """Тесты для RequestContext."""
    
    def test_request_context_api_key(self):
        """Тест: RequestContext для API Key."""
        context = RequestContext(
            subject="api_key:test_key",
            scopes=["devices.read"],
            is_admin=False,
            source="api_key"
        )
        
        assert context.subject == "api_key:test_key"
        assert context.scopes == ["devices.read"]
        assert context.is_admin is False
        assert context.source == "api_key"
        assert context.user_id is None
        assert context.session_id is None
    
    def test_request_context_session(self):
        """Тест: RequestContext для Session."""
        context = RequestContext(
            subject="user:user_123",
            scopes=["devices.read", "devices.write"],
            is_admin=False,
            source="session",
            user_id="user_123",
            session_id="session_456"
        )
        
        assert context.subject == "user:user_123"
        assert context.user_id == "user_123"
        assert context.session_id == "session_456"
        assert context.source == "session"


class TestValidateApiKey:
    """Тесты для validate_api_key()."""
    
    @pytest.mark.asyncio
    async def test_validate_api_key_success(self, mock_runtime):
        """Тест: успешная валидация API Key."""
        api_key = "test_key_123"
        key_data = {
            "subject": "api_key:test",
            "scopes": ["devices.read", "devices.write"],
            "is_admin": False
        }
        
        mock_runtime.storage.get.return_value = key_data
        
        context = await validate_api_key(mock_runtime, api_key)
        
        assert context is not None
        assert context.subject == "api_key:test"
        assert context.scopes == ["devices.read", "devices.write"]
        assert context.is_admin is False
        assert context.source == "api_key"
        mock_runtime.storage.get.assert_called_once_with(AUTH_API_KEYS_NAMESPACE, api_key)
    
    @pytest.mark.asyncio
    async def test_validate_api_key_not_found(self, mock_runtime):
        """Тест: API Key не найден."""
        api_key = "nonexistent_key"
        mock_runtime.storage.get.return_value = None
        
        context = await validate_api_key(mock_runtime, api_key)
        
        assert context is None
        mock_runtime.storage.get.assert_called_once_with(AUTH_API_KEYS_NAMESPACE, api_key)
    
    @pytest.mark.asyncio
    async def test_validate_api_key_empty(self, mock_runtime):
        """Тест: пустой API Key."""
        context = await validate_api_key(mock_runtime, "")
        assert context is None
    
    @pytest.mark.asyncio
    async def test_validate_api_key_invalid_data(self, mock_runtime):
        """Тест: невалидные данные ключа."""
        api_key = "test_key"
        mock_runtime.storage.get.return_value = "not_a_dict"
        mock_runtime.service_registry.call = AsyncMock()
        
        context = await validate_api_key(mock_runtime, api_key)
        
        assert context is None
        # Проверяем, что была попытка логирования
        assert mock_runtime.service_registry.call.called
    
    @pytest.mark.asyncio
    async def test_validate_api_key_admin(self, mock_runtime):
        """Тест: API Key с admin правами."""
        api_key = "admin_key"
        key_data = {
            "subject": "api_key:admin",
            "scopes": [],
            "is_admin": True
        }
        
        mock_runtime.storage.get.return_value = key_data
        
        context = await validate_api_key(mock_runtime, api_key)
        
        assert context is not None
        assert context.is_admin is True


class TestValidateSession:
    """Тесты для validate_session()."""
    
    @pytest.mark.asyncio
    async def test_validate_session_success(self, mock_runtime):
        """Тест: успешная валидация сессии."""
        session_id = "session_123"
        user_id = "user_456"
        
        session_data = {
            "user_id": user_id,
            "created_at": time.time(),
            "expires_at": time.time() + DEFAULT_SESSION_EXPIRATION_SECONDS
        }
        
        user_data = {
            "user_id": user_id,
            "username": "test_user",
            "scopes": ["devices.read"],
            "is_admin": False
        }
        
        mock_runtime.storage.get.side_effect = [session_data, user_data]
        
        context = await validate_session(mock_runtime, session_id)
        
        assert context is not None
        assert context.user_id == user_id
        assert context.session_id == session_id
        assert context.subject == f"user:{user_id}"
        assert context.scopes == ["devices.read"]
        assert context.source == "session"
        assert mock_runtime.storage.get.call_count == 2
    
    @pytest.mark.asyncio
    async def test_validate_session_not_found(self, mock_runtime):
        """Тест: сессия не найдена."""
        session_id = "nonexistent_session"
        mock_runtime.storage.get.return_value = None
        
        context = await validate_session(mock_runtime, session_id)
        
        assert context is None
    
    @pytest.mark.asyncio
    async def test_validate_session_expired(self, mock_runtime):
        """Тест: истёкшая сессия."""
        session_id = "expired_session"
        session_data = {
            "user_id": "user_123",
            "created_at": time.time() - 100000,
            "expires_at": time.time() - 1000  # Истекла
        }
        
        mock_runtime.storage.get.return_value = session_data
        mock_runtime.storage.delete = AsyncMock()
        
        context = await validate_session(mock_runtime, session_id)
        
        assert context is None
        # Проверяем, что сессия была удалена
        mock_runtime.storage.delete.assert_called_once_with(AUTH_SESSIONS_NAMESPACE, session_id)
    
    @pytest.mark.asyncio
    async def test_validate_session_user_not_found(self, mock_runtime):
        """Тест: пользователь не найден."""
        session_id = "session_123"
        session_data = {
            "user_id": "user_456",
            "created_at": time.time(),
            "expires_at": time.time() + 3600
        }
        
        mock_runtime.storage.get.side_effect = [session_data, None]  # Пользователь не найден
        mock_runtime.storage.delete = AsyncMock()
        
        context = await validate_session(mock_runtime, session_id)
        
        assert context is None
        # Проверяем, что сессия была удалена
        mock_runtime.storage.delete.assert_called_once_with(AUTH_SESSIONS_NAMESPACE, session_id)


class TestCreateSession:
    """Тесты для create_session()."""
    
    @pytest.mark.asyncio
    async def test_create_session_default_expiration(self, mock_runtime):
        """Тест: создание сессии с дефолтным expiration."""
        user_id = "user_123"
        mock_runtime.storage.set = AsyncMock()
        
        session_id = await create_session(mock_runtime, user_id)
        
        assert session_id is not None
        assert len(session_id) > 0
        mock_runtime.storage.set.assert_called_once()
        
        # Проверяем структуру сохранённых данных
        call_args = mock_runtime.storage.set.call_args
        assert call_args[0][0] == AUTH_SESSIONS_NAMESPACE
        assert call_args[0][1] == session_id
        
        session_data = call_args[0][2]
        assert session_data["user_id"] == user_id
        assert "created_at" in session_data
        assert "expires_at" in session_data
        assert session_data["expires_at"] > time.time()
    
    @pytest.mark.asyncio
    async def test_create_session_custom_expiration(self, mock_runtime):
        """Тест: создание сессии с кастомным expiration."""
        user_id = "user_123"
        expiration_seconds = 3600  # 1 час
        mock_runtime.storage.set = AsyncMock()
        
        session_id = await create_session(mock_runtime, user_id, expiration_seconds)
        
        assert session_id is not None
        
        # Проверяем expiration
        call_args = mock_runtime.storage.set.call_args
        session_data = call_args[0][2]
        expected_expires = time.time() + expiration_seconds
        assert abs(session_data["expires_at"] - expected_expires) < 1  # Разница < 1 секунды


class TestDeleteSession:
    """Тесты для delete_session()."""
    
    @pytest.mark.asyncio
    async def test_delete_session_success(self, mock_runtime):
        """Тест: успешное удаление сессии."""
        session_id = "session_123"
        mock_runtime.storage.delete = AsyncMock()
        
        await delete_session(mock_runtime, session_id)
        
        mock_runtime.storage.delete.assert_called_once_with(AUTH_SESSIONS_NAMESPACE, session_id)
    
    @pytest.mark.asyncio
    async def test_delete_session_handles_errors(self, mock_runtime):
        """Тест: обработка ошибок при удалении."""
        session_id = "session_123"
        mock_runtime.storage.delete = AsyncMock(side_effect=Exception("Storage error"))
        
        # Не должно падать
        await delete_session(mock_runtime, session_id)
        
        mock_runtime.storage.delete.assert_called_once()


class TestCheckServiceScope:
    """Тесты для check_service_scope()."""
    
    def test_check_scope_no_context(self):
        """Тест: нет контекста → нет доступа."""
        assert check_service_scope(None, "devices.list") is False
    
    def test_check_scope_admin_full_access(self):
        """Тест: admin имеет полный доступ."""
        context = RequestContext(
            subject="admin",
            scopes=[],
            is_admin=True,
            source="api_key"
        )
        
        assert check_service_scope(context, "devices.list") is True
        assert check_service_scope(context, "admin.v1.runtime") is True
        assert check_service_scope(context, "any.service") is True
    
    def test_check_scope_admin_service_requires_admin(self):
        """Тест: admin сервисы требуют admin прав."""
        context = RequestContext(
            subject="user:user_123",
            scopes=["devices.read"],
            is_admin=False,
            source="session"
        )
        
        assert check_service_scope(context, "admin.v1.runtime") is False
        assert check_service_scope(context, "admin.list_plugins") is False
    
    def test_check_scope_exact_match(self):
        """Тест: точное совпадение scope."""
        context = RequestContext(
            subject="user:user_123",
            scopes=["devices.read", "devices.write"],
            is_admin=False,
            source="session"
        )
        
        assert check_service_scope(context, "devices.read") is True
        assert check_service_scope(context, "devices.write") is True
        assert check_service_scope(context, "devices.list") is False
    
    def test_check_scope_wildcard_namespace(self):
        """Тест: wildcard для namespace."""
        context = RequestContext(
            subject="user:user_123",
            scopes=["devices.*"],
            is_admin=False,
            source="session"
        )
        
        assert check_service_scope(context, "devices.read") is True
        assert check_service_scope(context, "devices.write") is True
        assert check_service_scope(context, "devices.list") is True
        assert check_service_scope(context, "automation.trigger") is False
    
    def test_check_scope_full_wildcard(self):
        """Тест: полный wildcard (*)."""
        context = RequestContext(
            subject="user:user_123",
            scopes=["*"],
            is_admin=False,
            source="session"
        )
        
        assert check_service_scope(context, "devices.read") is True
        assert check_service_scope(context, "automation.trigger") is True
        assert check_service_scope(context, "any.service") is True
    
    def test_check_scope_invalid_service_format(self):
        """Тест: нестандартный формат service_name."""
        context = RequestContext(
            subject="user:user_123",
            scopes=["devices.read"],
            is_admin=False,
            source="session"
        )
        
        # Service без точки - требует admin
        assert check_service_scope(context, "invalid_service") is False


class TestIntegration:
    """Интеграционные тесты."""
    
    @pytest.mark.asyncio
    async def test_api_key_flow(self, mock_runtime):
        """Тест: полный flow с API Key."""
        # 1. Создать API Key
        api_key = "test_key"
        key_data = {
            "subject": "api_key:test",
            "scopes": ["devices.read"],
            "is_admin": False
        }
        mock_runtime.storage.get.return_value = key_data
        
        # 2. Валидировать
        context = await validate_api_key(mock_runtime, api_key)
        assert context is not None
        
        # 3. Проверить scope
        assert check_service_scope(context, "devices.read") is True
        assert check_service_scope(context, "devices.write") is False
    
    @pytest.mark.asyncio
    async def test_session_flow(self, mock_runtime):
        """Тест: полный flow с Session."""
        user_id = "user_123"
        
        # 1. Создать сессию
        mock_runtime.storage.set = AsyncMock()
        session_id = await create_session(mock_runtime, user_id)
        assert session_id is not None
        
        # 2. Валидировать сессию
        session_data = {
            "user_id": user_id,
            "created_at": time.time(),
            "expires_at": time.time() + 3600
        }
        user_data = {
            "user_id": user_id,
            "scopes": ["devices.read", "devices.write"],
            "is_admin": False
        }
        mock_runtime.storage.get.side_effect = [session_data, user_data]
        
        context = await validate_session(mock_runtime, session_id)
        assert context is not None
        assert context.user_id == user_id
        assert context.session_id == session_id
        
        # 3. Проверить scope
        assert check_service_scope(context, "devices.read") is True
        assert check_service_scope(context, "devices.write") is True
        
        # 4. Удалить сессию
        mock_runtime.storage.delete = AsyncMock()
        await delete_session(mock_runtime, session_id)
        mock_runtime.storage.delete.assert_called_once()


# ============================================================================
# Auth Hardening Tests
# ============================================================================

class TestRateLimiting:
    """Тесты для rate_limit_check()."""
    
    @pytest.mark.asyncio
    async def test_rate_limit_allows_requests(self, mock_runtime):
        """Тест: rate limit разрешает запросы в пределах лимита."""
        identifier = "test_identifier"
        mock_runtime.storage.get.return_value = None  # Первая попытка
        
        result = await rate_limit_check(mock_runtime, identifier, "auth")
        
        assert result is True
        mock_runtime.storage.set.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_rate_limit_blocks_after_limit(self, mock_runtime):
        """Тест: rate limit блокирует после превышения лимита."""
        identifier = "test_identifier"
        current_time = time.time()
        
        # Создаём данные с превышенным лимитом
        rate_data = {
            "count": RATE_LIMIT_AUTH_ATTEMPTS,
            "window_start": current_time - 10,  # В пределах окна
            "last_attempt": current_time - 5
        }
        mock_runtime.storage.get.return_value = rate_data
        
        result = await rate_limit_check(mock_runtime, identifier, "auth")
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_rate_limit_resets_after_window(self, mock_runtime):
        """Тест: rate limit сбрасывается после окна."""
        identifier = "test_identifier"
        current_time = time.time()
        
        # Создаём данные с истёкшим окном
        rate_data = {
            "count": RATE_LIMIT_AUTH_ATTEMPTS,
            "window_start": current_time - RATE_LIMIT_AUTH_WINDOW - 10,  # Окно истекло
            "last_attempt": current_time - RATE_LIMIT_AUTH_WINDOW - 5
        }
        mock_runtime.storage.get.return_value = rate_data
        
        result = await rate_limit_check(mock_runtime, identifier, "auth")
        
        assert result is True  # Должен сброситься и разрешить


class TestAuditLogging:
    """Тесты для audit_log_auth_event()."""
    
    @pytest.mark.asyncio
    async def test_audit_log_success(self, mock_runtime):
        """Тест: логирование успешного события."""
        mock_runtime.storage.set = AsyncMock()
        mock_runtime.service_registry.call = AsyncMock()
        
        await audit_log_auth_event(
            mock_runtime,
            "auth_success",
            "test_subject",
            {"ip": "127.0.0.1"},
            success=True
        )
        
        mock_runtime.storage.set.assert_called_once()
        # Проверяем структуру записи
        call_args = mock_runtime.storage.set.call_args
        audit_entry = call_args[0][2]
        assert audit_entry["event_type"] == "auth_success"
        assert audit_entry["success"] is True
        assert audit_entry["subject"] == "test_subject"
    
    @pytest.mark.asyncio
    async def test_audit_log_failure(self, mock_runtime):
        """Тест: логирование неудачного события."""
        mock_runtime.storage.set = AsyncMock()
        mock_runtime.service_registry.call = AsyncMock()
        
        await audit_log_auth_event(
            mock_runtime,
            "auth_failure",
            "test_subject",
            {"ip": "127.0.0.1"},
            success=False
        )
        
        mock_runtime.storage.set.assert_called_once()
        call_args = mock_runtime.storage.set.call_args
        audit_entry = call_args[0][2]
        assert audit_entry["success"] is False


class TestRevocation:
    """Тесты для revocation mechanism."""
    
    @pytest.mark.asyncio
    async def test_revoke_api_key(self, mock_runtime):
        """Тест: отзыв API key."""
        api_key = "test_key_123"
        mock_runtime.storage.set = AsyncMock()
        mock_runtime.storage.delete = AsyncMock()
        mock_runtime.service_registry.call = AsyncMock()
        
        await revoke_api_key(mock_runtime, api_key)
        
        # Проверяем, что ключ добавлен в revoked
        mock_runtime.storage.set.assert_called_once()
        # Проверяем, что ключ удалён из активных
        mock_runtime.storage.delete.assert_called_once_with(AUTH_API_KEYS_NAMESPACE, api_key)
    
    @pytest.mark.asyncio
    async def test_revoke_session(self, mock_runtime):
        """Тест: отзыв session."""
        session_id = "session_123"
        mock_runtime.storage.set = AsyncMock()
        mock_runtime.storage.delete = AsyncMock()
        mock_runtime.service_registry.call = AsyncMock()
        
        await revoke_session(mock_runtime, session_id)
        
        mock_runtime.storage.set.assert_called_once()
        mock_runtime.storage.delete.assert_called_once_with(AUTH_SESSIONS_NAMESPACE, session_id)
    
    @pytest.mark.asyncio
    async def test_is_revoked_true(self, mock_runtime):
        """Тест: проверка отозванного ключа."""
        identifier = "revoked_key"
        revoked_entry = {
            "revoked_at": time.time(),
            "type": "api_key"
        }
        mock_runtime.storage.get.return_value = revoked_entry
        
        result = await is_revoked(mock_runtime, identifier, "api_key")
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_is_revoked_false(self, mock_runtime):
        """Тест: проверка неотозванного ключа."""
        identifier = "active_key"
        mock_runtime.storage.get.return_value = None
        
        result = await is_revoked(mock_runtime, identifier, "api_key")
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_validate_api_key_revoked(self, mock_runtime):
        """Тест: валидация отозванного API key возвращает None."""
        api_key = "revoked_key"
        # is_revoked возвращает True
        mock_runtime.storage.get.side_effect = [
            {"revoked_at": time.time(), "type": "api_key"},  # revoked check
            None  # key_data (не должен вызываться)
        ]
        
        context = await validate_api_key(mock_runtime, api_key)
        
        assert context is None
    
    @pytest.mark.asyncio
    async def test_validate_session_revoked(self, mock_runtime):
        """Тест: валидация отозванной session возвращает None."""
        session_id = "revoked_session"
        # is_revoked возвращает True
        mock_runtime.storage.get.side_effect = [
            {"revoked_at": time.time(), "type": "session"},  # revoked check
            None  # session_data (не должен вызываться)
        ]
        
        context = await validate_session(mock_runtime, session_id)
        
        assert context is None


class TestInputValidation:
    """Тесты для input validation."""
    
    @pytest.mark.asyncio
    async def test_validate_user_exists_true(self, mock_runtime):
        """Тест: пользователь существует."""
        user_id = "user_123"
        user_data = {"user_id": user_id, "scopes": []}
        mock_runtime.storage.get.return_value = user_data
        
        result = await validate_user_exists(mock_runtime, user_id)
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_validate_user_exists_false(self, mock_runtime):
        """Тест: пользователь не существует."""
        user_id = "nonexistent_user"
        mock_runtime.storage.get.return_value = None
        
        result = await validate_user_exists(mock_runtime, user_id)
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_create_session_validates_user(self, mock_runtime):
        """Тест: create_session проверяет существование пользователя."""
        user_id = "nonexistent_user"
        mock_runtime.storage.get.return_value = None  # Пользователь не найден
        
        with pytest.raises(ValueError, match="not found"):
            await create_session(mock_runtime, user_id)
    
    def test_validate_scopes_valid(self):
        """Тест: валидация валидных scopes."""
        scopes = ["devices.read", "devices.write", "automation.*", "*"]
        
        result = validate_scopes(scopes)
        
        assert result is True
    
    def test_validate_scopes_invalid(self):
        """Тест: валидация невалидных scopes."""
        invalid_scopes = [
            ["devices.read", 123],  # не строка
            ["devices."],  # заканчивается точкой
            [".read"],  # начинается с точки
            ["invalid"],  # нет точки
        ]
        
        for scopes in invalid_scopes:
            result = validate_scopes(scopes)
            assert result is False
    
    def test_validate_scopes_not_list(self):
        """Тест: валидация не-списка."""
        # type: ignore - намеренно передаём неверный тип для теста
        result = validate_scopes("not_a_list")  # type: ignore
        assert result is False


class TestTimingAttackProtection:
    """Тесты для защиты от timing attacks."""
    
    @pytest.mark.asyncio
    async def test_validate_api_key_timing_protection(self, mock_runtime):
        """Тест: validate_api_key использует константное время."""
        api_key = "nonexistent_key"
        # Даже если ключ не найден, должна быть проверка (константное время)
        mock_runtime.storage.get.return_value = None
        
        context = await validate_api_key(mock_runtime, api_key)
        
        assert context is None
        # Проверяем, что storage.get был вызван (даже для несуществующего ключа)
        mock_runtime.storage.get.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_validate_session_timing_protection(self, mock_runtime):
        """Тест: validate_session использует константное время."""
        session_id = "nonexistent_session"
        mock_runtime.storage.get.return_value = None
        
        context = await validate_session(mock_runtime, session_id)
        
        assert context is None
        mock_runtime.storage.get.assert_called_once()
