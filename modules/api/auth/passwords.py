"""
Password management — хеширование, валидация и управление паролями.
"""

from typing import Any, Optional, Tuple
import re
import bcrypt

from .constants import (
    MIN_PASSWORD_LENGTH,
    MAX_PASSWORD_LENGTH,
    REQUIRE_UPPERCASE,
    REQUIRE_LOWERCASE,
    REQUIRE_DIGIT,
    REQUIRE_SPECIAL_CHAR
)
from .users import validate_user_exists
from .audit import audit_log_auth_event
from .constants import AUTH_USERS_NAMESPACE
from .sessions import revoke_all_sessions


def hash_password(password: str) -> str:
    """
    Хеширует пароль используя bcrypt.
    
    Args:
        password: пароль в открытом виде
    
    Returns:
        Хешированный пароль (строка)
    """
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')


def verify_password(password: str, password_hash: str) -> bool:
    """
    Проверяет пароль против хеша.
    
    Args:
        password: пароль в открытом виде
        password_hash: хеш пароля из storage
    
    Returns:
        True если пароль совпадает, False если нет
    """
    try:
        return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
    except Exception:
        return False


def validate_password_strength(password: str) -> Tuple[bool, Optional[str]]:
    """
    Валидирует силу пароля согласно политикам.
    
    Args:
        password: пароль для проверки
    
    Returns:
        (is_valid, error_message) - True если валиден, иначе False с сообщением об ошибке
    """
    if not isinstance(password, str):
        return False, "Password must be a string"
    
    if len(password) < MIN_PASSWORD_LENGTH:
        return False, f"Password must be at least {MIN_PASSWORD_LENGTH} characters long"
    
    if len(password) > MAX_PASSWORD_LENGTH:
        return False, f"Password must be at most {MAX_PASSWORD_LENGTH} characters long"
    
    if REQUIRE_UPPERCASE and not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter"
    
    if REQUIRE_LOWERCASE and not re.search(r'[a-z]', password):
        return False, "Password must contain at least one lowercase letter"
    
    if REQUIRE_DIGIT and not re.search(r'\d', password):
        return False, "Password must contain at least one digit"
    
    if REQUIRE_SPECIAL_CHAR and not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False, "Password must contain at least one special character"
    
    return True, None


async def set_password(runtime: Any, user_id: str, password: str) -> None:
    """
    Устанавливает пароль для пользователя.
    
    Args:
        runtime: экземпляр CoreRuntime
        user_id: ID пользователя
        password: пароль в открытом виде
    
    Raises:
        ValueError: если пользователь не существует или пароль не соответствует политикам
    """
    import time
    
    # Валидация существования пользователя
    if not await validate_user_exists(runtime, user_id):
        raise ValueError(f"User {user_id} not found")
    
    # Валидация силы пароля
    is_valid, error_message = validate_password_strength(password)
    if not is_valid:
        raise ValueError(error_message)
    
    # Хешируем пароль
    password_hash = hash_password(password)
    
    # Получаем данные пользователя
    user_data = await runtime.storage.get(AUTH_USERS_NAMESPACE, user_id)
    if not isinstance(user_data, dict):
        raise ValueError(f"Invalid user data for {user_id}")
    
    # Обновляем password hash
    user_data["password_hash"] = password_hash
    user_data["password_set_at"] = time.time()
    
    # Сохраняем обновлённые данные
    await runtime.storage.set(AUTH_USERS_NAMESPACE, user_id, user_data)
    
    # Audit logging
    await audit_log_auth_event(
        runtime,
        "password_set",
        user_id,
        {"password_set_at": user_data["password_set_at"]},
        success=True
    )


async def change_password(runtime: Any, user_id: str, old_password: str, new_password: str) -> None:
    """
    Меняет пароль пользователя.
    
    Args:
        runtime: экземпляр CoreRuntime
        user_id: ID пользователя
        old_password: текущий пароль
        new_password: новый пароль
    
    Raises:
        ValueError: если пользователь не существует, старый пароль неверен или новый пароль не соответствует политикам
    """
    import time
    
    # Валидация существования пользователя
    if not await validate_user_exists(runtime, user_id):
        raise ValueError(f"User {user_id} not found")
    
    # Получаем данные пользователя
    user_data = await runtime.storage.get(AUTH_USERS_NAMESPACE, user_id)
    if not isinstance(user_data, dict):
        raise ValueError(f"Invalid user data for {user_id}")
    
    # Проверяем, что у пользователя установлен пароль
    password_hash = user_data.get("password_hash")
    if not password_hash:
        raise ValueError(f"User {user_id} has no password set")
    
    # Проверяем старый пароль
    if not verify_password(old_password, password_hash):
        await audit_log_auth_event(
            runtime,
            "password_change_failed",
            user_id,
            {"reason": "incorrect_old_password"},
            success=False
        )
        raise ValueError("Incorrect old password")
    
    # Валидация нового пароля
    is_valid, error_message = validate_password_strength(new_password)
    if not is_valid:
        raise ValueError(error_message)
    
    # Проверяем, что новый пароль отличается от старого
    if verify_password(new_password, password_hash):
        raise ValueError("New password must be different from old password")
    
    # Хешируем новый пароль
    new_password_hash = hash_password(new_password)
    
    # Обновляем password hash
    user_data["password_hash"] = new_password_hash
    user_data["password_set_at"] = time.time()
    user_data["password_changed_at"] = time.time()
    
    # Сохраняем обновлённые данные
    await runtime.storage.set(AUTH_USERS_NAMESPACE, user_id, user_data)
    
    # Audit logging
    await audit_log_auth_event(
        runtime,
        "password_changed",
        user_id,
        {"password_changed_at": user_data["password_changed_at"]},
        success=True
    )
    
    # Отзываем все сессии пользователя при смене пароля
    try:
        await revoke_all_sessions(runtime, user_id)
    except Exception:
        pass


async def verify_user_password(runtime: Any, user_id: str, password: str) -> bool:
    """
    Проверяет пароль пользователя.
    
    Args:
        runtime: экземпляр CoreRuntime
        user_id: ID пользователя
        password: пароль для проверки
    
    Returns:
        True если пароль верен, False если нет или пароль не установлен
    """
    try:
        user_data = await runtime.storage.get(AUTH_USERS_NAMESPACE, user_id)
        if not isinstance(user_data, dict):
            return False
        
        password_hash = user_data.get("password_hash")
        if not password_hash:
            return False
        
        return verify_password(password, password_hash)
    except Exception:
        return False
