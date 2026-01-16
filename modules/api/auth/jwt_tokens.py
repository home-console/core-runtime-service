"""
JWT Token management — создание, валидация и управление JWT access/refresh tokens.
"""

from typing import Any, Optional, List, Set, Union, Dict, Tuple
import time
import secrets
import jwt
from jwt.exceptions import InvalidTokenError, ExpiredSignatureError
from fastapi import Request

from .context import RequestContext
from .constants import (
    AUTH_USERS_NAMESPACE,
    AUTH_REFRESH_TOKENS_NAMESPACE,
    JWT_ALGORITHM,
    JWT_SECRET_KEY_LENGTH,
    ACCESS_TOKEN_EXPIRATION_SECONDS,
    REFRESH_TOKEN_EXPIRATION_SECONDS,
    JWT_SECRET_KEY_STORAGE_KEY
)
from .revocation import is_revoked, revoke_refresh_token
from .audit import audit_log_auth_event
from .users import validate_user_exists


# In-memory cache для JWT secret чтобы избежать race condition
_jwt_secret_cache: Optional[str] = None


def extract_jwt_from_header(request: Request) -> Optional[str]:
    """
    Извлекает JWT access token из заголовка Authorization: Bearer <token>.
    
    Проверяет формат JWT (3 части через точку: header.payload.signature).
    
    Args:
        request: FastAPI Request
    
    Returns:
        JWT token или None если заголовок отсутствует/неверный формат или не JWT
    """
    auth_header = request.headers.get("Authorization", "")
    
    if not auth_header:
        return None
    
    # Поддерживаем формат "Bearer <token>"
    parts = auth_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    
    token = parts[1].strip()
    if not token:
        return None
    
    # SECURITY FIX: Проверяем, что это действительно JWT (3 части через точку)
    # JWT имеет формат: header.payload.signature
    token_parts = token.split(".")
    if len(token_parts) != 3:
        # Не JWT формат - это может быть API key
        return None
    
    # Дополнительная проверка: JWT части должны быть base64url encoded
    # Минимальная длина каждой части (даже для пустого payload)
    if any(len(part) < 4 for part in token_parts):
        return None
    
    return token


async def get_or_create_jwt_secret(runtime: Any) -> str:
    """
    Получает или создаёт JWT secret key.
    
    Args:
        runtime: экземпляр CoreRuntime
    
    Returns:
        JWT secret key (строка)
    """
    global _jwt_secret_cache
    
    # Сначала проверяем кеш в памяти
    if _jwt_secret_cache:
        return _jwt_secret_cache
    
    # Пытаемся загрузить из storage
    try:
        data = await runtime.storage.get("auth_config", JWT_SECRET_KEY_STORAGE_KEY)
        if data and isinstance(data, dict):
            secret = data.get("value")
            if secret and isinstance(secret, str):
                # Убрано избыточное логирование загрузки секрета
                _jwt_secret_cache = secret
                return secret
    except Exception as e:
        try:
            await runtime.service_registry.call(
                "logger.log",
                level="warning",
                message="Failed to load JWT secret from storage",
                module="auth",
                error=str(e)
            )
        except Exception:
            pass
    
    # Генерируем новый secret
    secret = secrets.token_urlsafe(JWT_SECRET_KEY_LENGTH)
    try:
        await runtime.service_registry.call(
            "logger.log",
            level="info",
            message="Generated new JWT secret",
            module="auth",
            secret_length=len(secret)
        )
    except Exception:
        pass
    try:
        # Оборачиваем в dict, так как storage.set требует dict
        await runtime.storage.set("auth_config", JWT_SECRET_KEY_STORAGE_KEY, {"value": secret})
        try:
            await runtime.service_registry.call(
                "logger.log",
                level="debug",
                message="Saved new JWT secret to storage",
                module="auth"
            )
        except Exception:
            pass
    except Exception as e:
        try:
            await runtime.service_registry.call(
                "logger.log",
                level="error",
                message="Failed to save JWT secret to storage",
                module="auth",
                error=str(e)
            )
        except Exception:
            pass
    
    # Кешируем в памяти
    _jwt_secret_cache = secret
    return secret


def generate_access_token(
    user_id: str,
    scopes: Union[List[str], Set[str]],
    is_admin: bool,
    secret: str,
    expiration_seconds: int = ACCESS_TOKEN_EXPIRATION_SECONDS
) -> str:
    """
    Генерирует JWT access token.
    
    Args:
        user_id: ID пользователя
        scopes: список или множество scopes
        is_admin: административные права
        secret: JWT secret key
        expiration_seconds: время жизни токена в секундах
    
    Returns:
        JWT token (строка)
    """
    # Конвертируем Set в List для JWT payload (Set не сериализуется в JSON)
    scopes_list = list(scopes) if isinstance(scopes, set) else scopes
    
    current_time = time.time()
    payload = {
        "user_id": user_id,
        "scopes": scopes_list,
        "is_admin": is_admin,
        "iat": current_time,  # issued at
        "exp": current_time + expiration_seconds,  # expiration
        "type": "access"
    }
    
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


async def validate_access_token(token: str, secret: str, runtime: Optional[Any] = None) -> Optional[Dict[str, Any]]:
    """
    Валидирует JWT access token.
    
    Args:
        token: JWT token
        secret: JWT secret key
        runtime: экземпляр CoreRuntime (опционально, для логирования)
    
    Returns:
        Payload если токен валиден, None если невалиден
    """
    try:
        payload = jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
        
        # Проверяем тип токена
        if payload.get("type") != "access":
            if runtime:
                try:
                    await runtime.service_registry.call(
                        "logger.log",
                        level="warning",
                        message="JWT token type mismatch",
                        module="auth",
                        expected_type="access",
                        actual_type=payload.get("type")
                    )
                except Exception:
                    pass
            return None
        
        # Убрано избыточное логирование успешной валидации токена
        return payload
    except ExpiredSignatureError:
        # Убрано избыточное логирование истекших токенов (нормальная ситуация)
        return None
    except InvalidTokenError as e:
        # Убрано избыточное логирование невалидных токенов (нормальная ситуация)
        return None
    except Exception as e:
        if runtime:
            try:
                await runtime.service_registry.call(
                    "logger.log",
                    level="warning",
                    message="JWT token validation error",
                    module="auth",
                    error=str(e)
                )
            except Exception:
                pass
        return None


async def validate_jwt_token(runtime: Any, token: str) -> Optional[RequestContext]:
    """
    Валидирует JWT access token и возвращает RequestContext.
    
    Args:
        runtime: экземпляр CoreRuntime
        token: JWT access token
    
    Returns:
        RequestContext если токен валиден, None если невалиден
    """
    try:
        # Получаем JWT secret
        secret = await get_or_create_jwt_secret(runtime)
        
        # Валидируем токен
        payload = await validate_access_token(token, secret, runtime)
        if not payload:
            return None
        
        user_id = payload.get("user_id")
        scopes_raw = payload.get("scopes", [])
        is_admin = payload.get("is_admin", False)
        
        if not user_id:
            return None
        
        # Нормализуем scopes в Set (для защиты от timing attacks и O(1) проверки)
        if isinstance(scopes_raw, list):
            scopes = set(scopes_raw)
        elif isinstance(scopes_raw, set):
            scopes = scopes_raw
        else:
            scopes = set()
        
        return RequestContext(
            subject=f"user:{user_id}",
            scopes=scopes,
            is_admin=is_admin,
            source="jwt",
            user_id=user_id
        )
    
    except Exception:
        return None


async def create_refresh_token(
    runtime: Any,
    user_id: str,
    expiration_seconds: Optional[int] = None,
    client_ip: Optional[str] = None,
    user_agent: Optional[str] = None
) -> str:
    """
    Создаёт refresh token и сохраняет его в storage.
    
    Args:
        runtime: экземпляр CoreRuntime
        user_id: ID пользователя
        expiration_seconds: время жизни токена (по умолчанию 7 дней)
        client_ip: IP адрес клиента (опционально)
        user_agent: User-Agent заголовок (опционально)
    
    Returns:
        Refresh token (строка)
    """
    if expiration_seconds is None:
        expiration_seconds = REFRESH_TOKEN_EXPIRATION_SECONDS
    
    # Генерируем уникальный refresh token
    refresh_token = secrets.token_urlsafe(32)
    
    current_time = time.time()
    expires_at = current_time + expiration_seconds
    
    # Сохраняем refresh token в storage
    token_data = {
        "user_id": user_id,
        "created_at": current_time,
        "expires_at": expires_at,
        "last_used": current_time,
    }
    
    if client_ip:
        token_data["client_ip"] = client_ip
    if user_agent:
        token_data["user_agent"] = user_agent[:256]
    
    await runtime.storage.set(AUTH_REFRESH_TOKENS_NAMESPACE, refresh_token, token_data)
    
    # Audit logging
    await audit_log_auth_event(
        runtime,
        "refresh_token_created",
        user_id,
        {
            "refresh_token": refresh_token[:16] + "...",
            "expiration_seconds": expiration_seconds,
            "client_ip": client_ip,
        },
        success=True
    )
    
    return refresh_token


async def validate_refresh_token(runtime: Any, refresh_token: str) -> Optional[Dict[str, Any]]:
    """
    Валидирует refresh token.
    
    Улучшенная проверка с защитой от race conditions.
    
    Args:
        runtime: экземпляр CoreRuntime
        refresh_token: refresh token для проверки
    
    Returns:
        Token data если валиден, None если невалиден
    """
    if not refresh_token or not refresh_token.strip():
        return None
    
    # SECURITY FIX: Проверка revocation ДО получения token_data
    # Это предотвращает race condition, когда токен отзывается между проверками
    if await is_revoked(runtime, refresh_token, "refresh_token"):
        return None
    
    try:
        token_data = await runtime.storage.get(AUTH_REFRESH_TOKENS_NAMESPACE, refresh_token)
        
        if not isinstance(token_data, dict):
            return None
        
        # SECURITY FIX: Повторная проверка revocation после получения данных
        # На случай, если токен был отозван между первой проверкой и получением данных
        if await is_revoked(runtime, refresh_token, "refresh_token"):
            return None
        
        # Проверяем expiration
        expires_at = token_data.get("expires_at")
        if expires_at:
            current_time = time.time()
            if current_time > expires_at:
                # Токен истёк - удаляем его
                try:
                    await runtime.storage.delete(AUTH_REFRESH_TOKENS_NAMESPACE, refresh_token)
                    # Отзываем токен для консистентности
                    await revoke_refresh_token(runtime, refresh_token)
                except Exception:
                    pass
                return None
        
        # Обновляем last_used
        token_data["last_used"] = time.time()
        await runtime.storage.set(AUTH_REFRESH_TOKENS_NAMESPACE, refresh_token, token_data)
        
        return token_data
    
    except Exception:
        return None


async def refresh_access_token(
    runtime: Any,
    refresh_token: str,
    rotate_refresh: bool = True
) -> Tuple[str, Optional[str]]:
    """
    Обновляет access token используя refresh token.
    
    Args:
        runtime: экземпляр CoreRuntime
        refresh_token: refresh token
        rotate_refresh: ротировать ли refresh token (рекомендуется True)
    
    Returns:
        (access_token, new_refresh_token) - new_refresh_token будет None если rotate_refresh=False
    
    Raises:
        ValueError: если refresh token невалиден
    """
    # Валидируем refresh token
    token_data = await validate_refresh_token(runtime, refresh_token)
    if not token_data:
        raise ValueError("Invalid or expired refresh token")
    
    user_id = token_data.get("user_id")
    if not user_id:
        raise ValueError("Invalid refresh token data")
    
    # Получаем данные пользователя
    user_data = await runtime.storage.get(AUTH_USERS_NAMESPACE, user_id)
    if not isinstance(user_data, dict):
        raise ValueError("User not found")
    
    scopes_raw = user_data.get("scopes", [])
    is_admin = user_data.get("is_admin", False)
    
    # Нормализуем scopes (могут быть list или set)
    scopes = list(scopes_raw) if isinstance(scopes_raw, (list, set)) else []
    
    # Получаем JWT secret
    secret = await get_or_create_jwt_secret(runtime)
    
    # Генерируем новый access token
    access_token = generate_access_token(user_id, scopes, is_admin, secret)
    
    # Ротируем refresh token (рекомендуется для безопасности)
    new_refresh_token = None
    if rotate_refresh:
        # Отзываем старый refresh token
        await revoke_refresh_token(runtime, refresh_token)
        
        # Создаём новый refresh token
        new_refresh_token = await create_refresh_token(
            runtime,
            user_id,
            client_ip=token_data.get("client_ip"),
            user_agent=token_data.get("user_agent")
        )
    
    # Audit logging
    await audit_log_auth_event(
        runtime,
        "token_refreshed",
        user_id,
        {"refresh_token": refresh_token[:16] + "...", "rotated": rotate_refresh},
        success=True
    )
    
    return access_token, new_refresh_token
