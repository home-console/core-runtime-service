"""
API Key management — создание, валидация, отзыв и ротация API keys.
"""

from typing import Any, Optional, List, Set, Union
import time
import secrets
from fastapi import Request

from .context import RequestContext
from .constants import AUTH_API_KEYS_NAMESPACE
from .revocation import is_revoked, revoke_api_key
from .audit import audit_log_auth_event
from .utils import validate_scopes


async def validate_api_key(runtime: Any, api_key: str) -> Optional[RequestContext]:
    """
    Валидирует API Key и возвращает RequestContext.
    
    Включает проверку revocation и защиту от timing attacks.
    
    Args:
        runtime: экземпляр CoreRuntime
        api_key: API ключ из заголовка Authorization: Bearer <key>
    
    Returns:
        RequestContext если ключ валиден, None если не найден
    """
    if not api_key or not api_key.strip():
        return None
    
    # Проверка revocation
    if await is_revoked(runtime, api_key, "api_key"):
        return None
    
    try:
        # Получаем данные ключа из storage
        key_data = await runtime.storage.get(AUTH_API_KEYS_NAMESPACE, api_key)
        
        # Timing attack protection
        if key_data is None:
            _ = secrets.compare_digest(api_key, api_key)
            return None
        
        # Проверяем структуру данных
        if not isinstance(key_data, dict):
            try:
                await runtime.service_registry.call(
                    "logger.log",
                    level="warning",
                    message=f"Invalid API key data structure for key: {api_key[:8]}...",
                    module="api"
                )
            except Exception:
                pass
            return None
        
        # Проверяем expiration
        expires_at = key_data.get("expires_at")
        if expires_at:
            current_time = time.time()
            if current_time > expires_at:
                try:
                    await runtime.storage.delete(AUTH_API_KEYS_NAMESPACE, api_key)
                    await revoke_api_key(runtime, api_key)
                except Exception:
                    pass
                return None
        
        # Извлекаем данные
        subject = key_data.get("subject", f"api_key:{api_key[:8]}")
        scopes_raw = key_data.get("scopes", [])
        is_admin = key_data.get("is_admin", False)
        user_id = key_data.get("user_id")  # Для Resource-Based Authorization с ACL
        
        # Нормализуем scopes в Set (для защиты от timing attacks и O(1) проверки)
        if isinstance(scopes_raw, list):
            scopes = set(scopes_raw)
        elif isinstance(scopes_raw, set):
            scopes = scopes_raw
        else:
            scopes = set()
        
        # Обновляем last_used
        current_time = time.time()
        last_used = key_data.get("last_used")
        if last_used is None or current_time - last_used >= 60:
            key_data["last_used"] = current_time
            await runtime.storage.set(AUTH_API_KEYS_NAMESPACE, api_key, key_data)
        
        return RequestContext(
            subject=subject,
            scopes=scopes,
            is_admin=is_admin,
            source="api_key",
            user_id=user_id  # Для поддержки ACL (ownership/shared)
        )
    
    except Exception as e:
        try:
            await runtime.service_registry.call(
                "logger.log",
                level="error",
                message=f"Error validating API key: {e}",
                module="api"
            )
        except Exception:
            pass
        return None


def extract_api_key_from_header(request) -> Optional[str]:
    """
    Извлекает API Key из заголовка Authorization: Bearer <key>.
    
    Args:
        request: FastAPI Request
    
    Returns:
        API key или None если заголовок отсутствует/неверный формат
    """
    
    auth_header = request.headers.get("Authorization", "")
    
    if not auth_header:
        return None
    
    # Поддерживаем формат "Bearer <token>"
    parts = auth_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    
    api_key = parts[1].strip()
    if not api_key:
        return None
    
    return api_key


async def create_api_key(
    runtime: Any,
    scopes: Union[List[str], Set[str]],
    is_admin: bool = False,
    subject: Optional[str] = None,
    expires_at: Optional[float] = None,
    user_id: Optional[str] = None
) -> str:
    """
    Создаёт новый API key.
    
    Args:
        runtime: экземпляр CoreRuntime
        scopes: список scopes (например, ["devices.read", "devices.write"])
        is_admin: является ли ключ административным
        subject: опциональный subject (по умолчанию генерируется)
        expires_at: опциональное время истечения (timestamp), None = без истечения
        user_id: опциональный ID пользователя (для Resource-Based Authorization с ACL)
    
    Returns:
        API key (строка)
    """
    # Валидация scopes (конвертируем Set в List для валидации, если нужно)
    scopes_list = list(scopes) if isinstance(scopes, set) else scopes
    if not validate_scopes(scopes_list):
        raise ValueError("Invalid scopes format")
    
    # Нормализуем в list для сохранения в storage (Set не сериализуется в JSON)
    scopes = scopes_list if isinstance(scopes_list, list) else list(scopes_list)
    
    # Проверка expires_at
    if expires_at is not None and expires_at <= time.time():
        raise ValueError("expires_at must be in the future")
    
    # Генерируем уникальный API key
    api_key = secrets.token_urlsafe(32)
    
    # Генерируем subject если не указан
    if subject is None:
        subject = f"api_key:{api_key[:8]}"
    
    current_time = time.time()
    
    # Сохраняем данные ключа
    key_data = {
        "subject": subject,
        "scopes": scopes,
        "is_admin": is_admin,
        "created_at": current_time,
        "last_used": None,
    }
    
    # Добавляем user_id, если указан (для Resource-Based Authorization с ACL)
    if user_id:
        key_data["user_id"] = user_id
    
    # Добавляем expires_at, если указано
    if expires_at is not None:
        key_data["expires_at"] = expires_at
    
    await runtime.storage.set(AUTH_API_KEYS_NAMESPACE, api_key, key_data)
    
    # Устанавливаем флаг создания первого ключа (для защиты от race condition)
    # Это делается после успешного создания ключа
    try:
        first_key_flag = await runtime.storage.get("auth_config", "first_key_created")
        if first_key_flag is None:
            # Проверяем, действительно ли это первый ключ
            all_keys = await runtime.storage.list_keys(AUTH_API_KEYS_NAMESPACE)
            if len(all_keys) == 1:  # Только что созданный ключ
                await runtime.storage.set("auth_config", "first_key_created", True)
    except Exception:
        # Игнорируем ошибки при установке флага
        pass
    
    # Audit logging
    await audit_log_auth_event(
        runtime,
        "key_created",
        subject,
        {"scopes": scopes, "is_admin": is_admin, "expires_at": expires_at, "user_id": user_id},
        success=True
    )
    
    return api_key


async def rotate_api_key(runtime: Any, old_api_key: str, expires_at: Optional[float] = None) -> str:
    """
    Ротирует API key: создаёт новый ключ и отзывает старый.
    
    Args:
        runtime: экземпляр CoreRuntime
        old_api_key: старый API ключ для ротации
        expires_at: опциональное время истечения для нового ключа
    
    Returns:
        Новый API key
    
    Raises:
        ValueError: если старый ключ не найден или невалиден
    """
    # Получаем данные старого ключа
    old_key_data = await runtime.storage.get(AUTH_API_KEYS_NAMESPACE, old_api_key)
    if not isinstance(old_key_data, dict):
        raise ValueError("Old API key not found or invalid")
    
    # Проверяем, не отозван ли уже ключ
    if await is_revoked(runtime, old_api_key, "api_key"):
        raise ValueError("Old API key is already revoked")
    
    # Извлекаем данные из старого ключа
    scopes_raw = old_key_data.get("scopes", [])
    is_admin = old_key_data.get("is_admin", False)
    subject = old_key_data.get("subject")
    user_id = old_key_data.get("user_id")  # Сохраняем user_id при ротации
    
    # Нормализуем scopes (могут быть list или set)
    scopes = list(scopes_raw) if isinstance(scopes_raw, (list, set)) else []
    
    # Создаём новый ключ с теми же правами
    new_api_key = await create_api_key(
        runtime,
        scopes=scopes,
        is_admin=is_admin,
        subject=subject,
        expires_at=expires_at,
        user_id=user_id  # Сохраняем user_id при ротации
    )
    
    # Отзываем старый ключ
    await revoke_api_key(runtime, old_api_key)
    
    # Audit logging
    await audit_log_auth_event(
        runtime,
        "key_rotated",
        old_api_key[:16] + "...",
        {
            "old_key": old_api_key[:16] + "...",
            "new_key": new_api_key[:16] + "...",
            "subject": subject
        },
        success=True
    )
    
    return new_api_key
