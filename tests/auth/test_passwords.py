"""
Тесты для modules/api/auth/passwords.py
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from modules.api.auth import (
    hash_password,
    verify_password,
    validate_password_strength,
    set_password,
    change_password,
    verify_user_password
)
from modules.api.auth.constants import AUTH_USERS_NAMESPACE


@pytest.fixture
def mock_runtime():
    """Mock CoreRuntime для изоляции тестов."""
    runtime = MagicMock()
    runtime.storage = AsyncMock()
    runtime.service_registry = AsyncMock()
    return runtime


class TestHashPassword:
    """Тесты для hash_password()."""
    
    def test_hash_password_returns_hash(self):
        """Тест: хеширование возвращает hash."""
        password = "SecurePassword123"
        
        password_hash = hash_password(password)
        
        assert password_hash is not None
        assert password_hash != password  # Не plain text
        assert len(password_hash) > 50  # bcrypt hash длинный
    
    def test_same_password_different_hashes(self):
        """Тест: одинаковый пароль дает разные хеши (salt)."""
        password = "SecurePassword123"
        
        hash1 = hash_password(password)
        hash2 = hash_password(password)
        
        assert hash1 != hash2  # Salt разный


class TestVerifyPassword:
    """Тесты для verify_password()."""
    
    def test_verify_correct_password(self):
        """Тест: проверка правильного пароля."""
        password = "SecurePassword123"
        password_hash = hash_password(password)
        
        result = verify_password(password, password_hash)
        
        assert result is True
    
    def test_verify_incorrect_password(self):
        """Тест: проверка неправильного пароля."""
        password = "SecurePassword123"
        wrong_password = "WrongPassword456"
        password_hash = hash_password(password)
        
        result = verify_password(wrong_password, password_hash)
        
        assert result is False
    
    def test_verify_empty_password(self):
        """Тест: пустой пароль не проходит."""
        password = "SecurePassword123"
        password_hash = hash_password(password)
        
        result = verify_password("", password_hash)
        
        assert result is False


class TestValidatePasswordStrength:
    """Тесты для validate_password_strength()."""
    
    def test_strong_password_passes(self):
        """Тест: сильный пароль проходит валидацию."""
        password = "SecurePassword123"
        
        is_valid, error = validate_password_strength(password)
        
        assert is_valid is True
        assert error is None
    
    def test_too_short_password_fails(self):
        """Тест: короткий пароль не проходит."""
        password = "Short1"
        
        is_valid, error = validate_password_strength(password)
        
        assert is_valid is False
        assert "character" in error.lower() or "at least" in error.lower()
    
    def test_no_uppercase_fails(self):
        """Тест: пароль без заглавных букв не проходит."""
        password = "securepassword123"
        
        is_valid, error = validate_password_strength(password)
        
        assert is_valid is False
        assert "uppercase" in error.lower()
    
    def test_no_lowercase_fails(self):
        """Тест: пароль без строчных букв не проходит."""
        password = "SECUREPASSWORD123"
        
        is_valid, error = validate_password_strength(password)
        
        assert is_valid is False
        assert "lowercase" in error.lower()
    
    def test_no_digit_fails(self):
        """Тест: пароль без цифр не проходит."""
        password = "SecurePassword"
        
        is_valid, error = validate_password_strength(password)
        
        assert is_valid is False
        assert "digit" in error.lower()
    
    def test_too_long_password_fails(self):
        """Тест: слишком длинный пароль не проходит."""
        password = "A" * 200 + "a1"
        
        is_valid, error = validate_password_strength(password)
        
        assert is_valid is False


class TestSetPassword:
    """Тесты для set_password()."""
    
    @pytest.mark.asyncio
    async def test_set_password_success(self, mock_runtime):
        """Тест: успешная установка пароля."""
        user_id = "user_test"
        password = "SecurePassword123"
        
        user_data = {
            "user_id": user_id,
            "username": "testuser",
            "scopes": []
        }
        
        mock_runtime.storage.get.return_value = user_data
        mock_runtime.storage.set.return_value = None
        
        with patch('modules.api.auth.passwords.validate_user_exists', new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = True
            
            await set_password(mock_runtime, user_id, password)
            
            # Verify password_hash was saved
            # storage.set вызывается дважды: один раз для пользователя, один раз для audit log
            call_args_list = mock_runtime.storage.set.call_args_list
            # Первый вызов - сохранение пользователя
            user_call = call_args_list[0]
            updated_data = user_call[0][2]
            assert "password_hash" in updated_data
            assert updated_data["password_hash"] != password  # Не plain text
    
    @pytest.mark.asyncio
    async def test_set_password_weak_password_fails(self, mock_runtime):
        """Тест: установка слабого пароля не работает."""
        user_id = "user_test"
        weak_password = "weak"
        
        user_data = {"user_id": user_id}
        mock_runtime.storage.get.return_value = user_data
        
        with pytest.raises(ValueError):
            await set_password(mock_runtime, user_id, weak_password)
    
    @pytest.mark.asyncio
    async def test_set_password_nonexistent_user_fails(self, mock_runtime):
        """Тест: установка пароля несуществующему пользователю."""
        mock_runtime.storage.get.return_value = None
        
        with pytest.raises(ValueError):
            await set_password(mock_runtime, "nonexistent", "SecurePassword123")


class TestChangePassword:
    """Тесты для change_password()."""
    
    @pytest.mark.asyncio
    async def test_change_password_success(self, mock_runtime):
        """Тест: успешная смена пароля."""
        user_id = "user_test"
        old_password = "OldPassword123"
        new_password = "NewPassword456"
        
        # Создаём хеш старого пароля
        old_hash = hash_password(old_password)
        
        user_data = {
            "user_id": user_id,
            "password_hash": old_hash
        }
        
        mock_runtime.storage.get.return_value = user_data
        mock_runtime.storage.set.return_value = None
        
        with patch('modules.api.auth.passwords.validate_user_exists', new_callable=AsyncMock) as mock_validate:
            with patch('modules.api.auth.passwords.revoke_all_sessions', new_callable=AsyncMock):
                mock_validate.return_value = True
                
                await change_password(mock_runtime, user_id, old_password, new_password)
                
                # Verify new password was saved
                # storage.set вызывается дважды: один раз для пользователя, один раз для audit log
                call_args_list = mock_runtime.storage.set.call_args_list
                # Первый вызов - сохранение пользователя
                user_call = call_args_list[0]
                updated_data = user_call[0][2]
                
                # Проверяем что новый пароль работает
                assert verify_password(new_password, updated_data["password_hash"])
                # Старый пароль больше не работает
                assert not verify_password(old_password, updated_data["password_hash"])
    
    @pytest.mark.asyncio
    async def test_change_password_wrong_old_password(self, mock_runtime):
        """Тест: смена пароля с неправильным старым."""
        user_id = "user_test"
        old_password = "OldPassword123"
        wrong_old = "WrongPassword"
        new_password = "NewPassword456"
        
        old_hash = hash_password(old_password)
        user_data = {"user_id": user_id, "password_hash": old_hash}
        
        mock_runtime.storage.get.return_value = user_data
        
        with patch('modules.api.auth.passwords.validate_user_exists', new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = True
            
            with pytest.raises(ValueError):
                await change_password(mock_runtime, user_id, wrong_old, new_password)


class TestVerifyUserPassword:
    """Тесты для verify_user_password()."""
    
    @pytest.mark.asyncio
    async def test_verify_user_password_correct(self, mock_runtime):
        """Тест: проверка правильного пароля пользователя."""
        user_id = "user_test"
        password = "SecurePassword123"
        password_hash = hash_password(password)
        
        user_data = {
            "user_id": user_id,
            "password_hash": password_hash
        }
        
        mock_runtime.storage.get.return_value = user_data
        
        result = await verify_user_password(mock_runtime, user_id, password)
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_verify_user_password_incorrect(self, mock_runtime):
        """Тест: проверка неправильного пароля."""
        user_id = "user_test"
        correct_password = "SecurePassword123"
        wrong_password = "WrongPassword456"
        
        password_hash = hash_password(correct_password)
        user_data = {"user_id": user_id, "password_hash": password_hash}
        
        mock_runtime.storage.get.return_value = user_data
        
        result = await verify_user_password(mock_runtime, user_id, wrong_password)
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_verify_user_password_no_hash_stored(self, mock_runtime):
        """Тест: пользователь без пароля."""
        user_id = "user_test"
        user_data = {"user_id": user_id}  # Нет password_hash
        
        mock_runtime.storage.get.return_value = user_data
        
        result = await verify_user_password(mock_runtime, user_id, "AnyPassword123")
        
        assert result is False
