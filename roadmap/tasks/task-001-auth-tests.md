# ✅ Task 001: Auth Module Tests

**Приоритет:** 🔴 КРИТИЧЕСКИЙ  
**Срок:** 8 часов  
**Ответственный:** Dev Team  
**Статус:** 🔴 Не начато

---

## 🎯 Цель

Создать полное покрытие тестами для `modules/api/auth/*` (14 модулей).

---

## 📋 Подзадачи

### 1. test_api_keys.py (1.5 часа)
Тестировать `modules/api/auth/api_keys.py`:
- [ ] validate_api_key() - валидный ключ
- [ ] validate_api_key() - невалидный ключ
- [ ] validate_api_key() - истекший ключ
- [ ] validate_api_key() - отозванный ключ
- [ ] create_api_key() - успешное создание
- [ ] create_api_key() - с expiration
- [ ] rotate_api_key() - ротация ключа
- [ ] extract_api_key_from_header() - парсинг заголовка

### 2. test_sessions.py (1.5 часа)
Тестировать `modules/api/auth/sessions.py`:
- [ ] validate_session() - валидная сессия
- [ ] validate_session() - истекшая сессия
- [ ] validate_session() - несуществующая сессия
- [ ] create_session() - создание сессии
- [ ] delete_session() - удаление сессии
- [ ] list_sessions() - список сессий пользователя
- [ ] revoke_all_sessions() - отзыв всех сессий
- [ ] extract_session_from_cookie() - парсинг cookie

### 3. test_jwt_tokens.py (1.5 часа)
Тестировать `modules/api/auth/jwt_tokens.py`:
- [ ] generate_access_token() - генерация токена
- [ ] validate_jwt_token() - валидация токена
- [ ] validate_jwt_token() - истекший токен
- [ ] validate_jwt_token() - невалидная подпись
- [ ] create_refresh_token() - refresh token
- [ ] validate_refresh_token() - валидация refresh
- [ ] refresh_access_token() - обновление access token
- [ ] get_or_create_jwt_secret() - генерация секрета

### 4. test_passwords.py (1 час)
Тестировать `modules/api/auth/passwords.py`:
- [ ] hash_password() - хеширование
- [ ] verify_password() - проверка пароля
- [ ] validate_password_strength() - сложность пароля
- [ ] set_password() - установка пароля пользователю
- [ ] change_password() - смена пароля
- [ ] verify_user_password() - проверка пароля пользователя

### 5. test_middleware.py (1 час)
Тестировать `modules/api/auth/middleware.py`:
- [ ] require_auth_middleware() - с валидным ключом
- [ ] require_auth_middleware() - без ключа (401)
- [ ] require_auth_middleware() - с невалидным ключом (401)
- [ ] get_request_context() - получение контекста

### 6. test_revocation.py (30 минут)
Тестировать `modules/api/auth/revocation.py`:
- [ ] revoke_api_key() - отзыв ключа
- [ ] revoke_session() - отзыв сессии
- [ ] revoke_refresh_token() - отзыв refresh token
- [ ] is_revoked() - проверка отзыва

### 7. test_audit.py (30 минут)
Тестировать `modules/api/auth/audit.py`:
- [ ] audit_log_auth_event() - успешная аутентификация
- [ ] audit_log_auth_event() - неудачная попытка

### 8. test_rate_limiting.py (30 минут)
Тестировать `modules/api/auth/rate_limiting.py`:
- [ ] rate_limit_check() - в пределах лимита
- [ ] rate_limit_check() - превышение лимита

### 9. test_users.py (30 минут)
Тестировать `modules/api/auth/users.py`:
- [ ] validate_user_exists() - существующий пользователь
- [ ] validate_user_exists() - несуществующий
- [ ] create_user() - создание пользователя

### 10. test_utils.py (30 минут)
Тестировать `modules/api/auth/utils.py`:
- [ ] validate_scopes() - валидация scopes
- [ ] check_service_scope() - проверка доступа

---

## 📝 Шаблон теста

```python
"""
Тесты для modules/api/auth/api_keys.py
"""
import pytest
import time
from unittest.mock import AsyncMock, MagicMock
from modules.api.auth import validate_api_key, create_api_key
from modules.api.auth.constants import AUTH_API_KEYS_NAMESPACE


@pytest.fixture
def mock_runtime():
    """Mock CoreRuntime для изоляции тестов."""
    runtime = MagicMock()
    runtime.storage = AsyncMock()
    runtime.service_registry = AsyncMock()
    return runtime


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
        assert context.subject == "user:test"
        assert "devices.read" in context.scopes
        assert context.is_admin is False
        assert context.source == "api_key"
        
        # Verify storage was called correctly
        mock_runtime.storage.get.assert_called_once_with(
            AUTH_API_KEYS_NAMESPACE,
            api_key
        )
    
    @pytest.mark.asyncio
    async def test_nonexistent_key_returns_none(self, mock_runtime):
        """Тест: несуществующий ключ возвращает None."""
        mock_runtime.storage.get.return_value = None
        
        context = await validate_api_key(mock_runtime, "invalid_key")
        
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
        
        # Verify storage.set was called
        mock_runtime.storage.set.assert_called_once()
        call_args = mock_runtime.storage.set.call_args
        assert call_args[0][0] == AUTH_API_KEYS_NAMESPACE
        assert call_args[0][1] == api_key
        
        key_data = call_args[0][2]
        assert key_data["subject"] == subject
        assert key_data["scopes"] == scopes
        assert key_data["is_admin"] is False
```

---

## ✅ Acceptance Criteria

- [ ] Все 10 тестовых файлов созданы
- [ ] Coverage для `modules/api/auth/*` > 90%
- [ ] Все тесты проходят (pytest)
- [ ] Нет warnings при запуске тестов
- [ ] Mock используются правильно (изоляция)
- [ ] Docstrings для всех тестов

---

## 🚀 Запуск

```bash
cd core-runtime-service

# Создать структуру
mkdir -p tests/auth

# Запустить тесты
pytest tests/auth/ -v --cov=modules/api/auth --cov-report=term-missing

# Проверить coverage
pytest tests/auth/ --cov=modules/api/auth --cov-report=html
open htmlcov/index.html
```

---

## 🔗 Ссылки

- **Roadmap:** [../ROADMAP.md](../../ROADMAP.md)
- **Testing Strategy:** [../01-testing-strategy.md](../01-testing-strategy.md)
- **Auth Module:** [../../core-runtime-service/modules/api/auth/](../../core-runtime-service/modules/api/auth/)

---

## 📊 Прогресс

**Статус:** 🔴 Не начато  
**Затрачено:** 0/8 часов  
**Дата начала:** TBD  
**Дата завершения:** TBD
