"""
User management — создание и валидация пользователей.
"""

from typing import Any, List, Set, Optional, Union
import time

from .constants import AUTH_USERS_NAMESPACE
from .audit import audit_log_auth_event
from .utils import validate_scopes


async def validate_user_exists(runtime: Any, user_id: str) -> bool:
    """
    Проверяет существование пользователя.
    
    Args:
        runtime: экземпляр CoreRuntime
        user_id: ID пользователя
    
    Returns:
        True если пользователь существует, False если нет
    """
    try:
        user_data = await runtime.storage.get(AUTH_USERS_NAMESPACE, user_id)
        return user_data is not None and isinstance(user_data, dict)
    except Exception:
        return False


async def create_user(
    runtime: Any,
    user_id: str,
    scopes: Union[List[str], Set[str]],
    is_admin: bool = False,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> None:
    """
    Создаёт нового пользователя.
    
    Args:
        runtime: экземпляр CoreRuntime
        user_id: уникальный ID пользователя
        scopes: список scopes
        is_admin: является ли пользователь администратором
        username: опциональное имя пользователя
        password: опциональный пароль (если не указан, пользователь должен будет установить его позже)
    
    Raises:
        ValueError: если scopes невалидны, пользователь уже существует или пароль не соответствует политикам
    """
    # Валидация scopes (конвертируем Set в List для валидации, если нужно)
    scopes_list = list(scopes) if isinstance(scopes, set) else scopes
    if not validate_scopes(scopes_list):
        raise ValueError("Invalid scopes format")
    
    # Нормализуем в list для сохранения в storage (Set не сериализуется в JSON)
    scopes = scopes_list if isinstance(scopes_list, list) else list(scopes_list)
    
    # Проверяем, не существует ли уже пользователь
    if await validate_user_exists(runtime, user_id):
        raise ValueError(f"User {user_id} already exists")
    
    # Валидация и хеширование пароля, если указан
    password_hash = None
    if password:
        # Lazy import для избежания циклической зависимости
        from .passwords import hash_password, validate_password_strength
        is_valid, error_message = validate_password_strength(password)
        if not is_valid:
            raise ValueError(error_message)
        password_hash = hash_password(password)
    
    # Сохраняем данные пользователя
    user_data = {
        "user_id": user_id,
        "username": username or user_id,
        "scopes": scopes,
        "is_admin": is_admin,
        "created_at": time.time()
    }
    
    # Добавляем password hash, если пароль указан
    if password_hash:
        user_data["password_hash"] = password_hash
        user_data["password_set_at"] = time.time()
    
    await runtime.storage.set(AUTH_USERS_NAMESPACE, user_id, user_data)
    
    # Audit logging
    await audit_log_auth_event(
        runtime,
        "user_created",
        user_id,
        {"username": username, "scopes": scopes, "is_admin": is_admin, "has_password": password_hash is not None},
        success=True
    )
