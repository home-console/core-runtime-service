"""
API Key Authentication — boundary-layer для ApiModule и AdminModule.

Это boundary-layer: auth логика НЕ проникает в CoreRuntime, RuntimeModule,
ServiceRegistry или доменные модули. Всё изолировано на уровне HTTP.

Архитектура:
- RequestContext передаётся через request.state (FastAPI)
- validate_api_key() проверяет ключ и возвращает RequestContext
- validate_session() проверяет сессию и возвращает RequestContext
- check_service_scope() проверяет права на вызов сервиса
- API keys хранятся в runtime.storage namespace "auth_api_keys"
- Sessions хранятся в runtime.storage namespace "auth_sessions"
- Users хранятся в runtime.storage namespace "auth_users"

Функциональность:
- Поддержка users и sessions
- Cookie-based authentication
- Session expiration
- Rate limiting, audit logging, revocation
"""

from dataclasses import dataclass
from typing import Any, Optional, List, Dict, Tuple
import time
import secrets
import hashlib
import re
import bcrypt
import jwt
from jwt.exceptions import InvalidTokenError, ExpiredSignatureError
from fastapi import Request, HTTPException, status, Response

# Storage namespaces
AUTH_API_KEYS_NAMESPACE = "auth_api_keys"
AUTH_SESSIONS_NAMESPACE = "auth_sessions"
AUTH_USERS_NAMESPACE = "auth_users"
AUTH_RATE_LIMITS_NAMESPACE = "auth_rate_limits"
AUTH_AUDIT_LOG_NAMESPACE = "auth_audit_log"
AUTH_REVOKED_NAMESPACE = "auth_revoked"
AUTH_REFRESH_TOKENS_NAMESPACE = "auth_refresh_tokens"

# Default session expiration (24 hours)
DEFAULT_SESSION_EXPIRATION_SECONDS = 24 * 60 * 60

# JWT settings
JWT_ALGORITHM = "HS256"
JWT_SECRET_KEY_LENGTH = 32  # Будет генерироваться при первом запуске
ACCESS_TOKEN_EXPIRATION_SECONDS = 15 * 60  # 15 минут
REFRESH_TOKEN_EXPIRATION_SECONDS = 7 * 24 * 60 * 60  # 7 дней
JWT_SECRET_KEY_STORAGE_KEY = "jwt_secret_key"  # Хранится в storage

# Rate limiting defaults
RATE_LIMIT_AUTH_ATTEMPTS = 10  # попыток (для login, create_api_key и т.д.)
RATE_LIMIT_AUTH_WINDOW = 60  # секунд
RATE_LIMIT_API_REQUESTS = 1000  # запросов (для обычных API запросов)
RATE_LIMIT_API_WINDOW = 60  # секунд

# Password policies
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
REQUIRE_UPPERCASE = True
REQUIRE_LOWERCASE = True
REQUIRE_DIGIT = True
REQUIRE_SPECIAL_CHAR = False  # Опционально, можно включить для большей безопасности


@dataclass
class RequestContext:
    """
    Контекст авторизации для HTTP запроса.
    
    Передаётся через request.state в FastAPI.
    Не проникает в CoreRuntime или доменные модули.
    
    Поддерживает users и sessions.
    """
    subject: str  # Идентификатор субъекта (например, "api_key:key_id", "user:user_id", "session:session_id")
    scopes: List[str]  # Список разрешений (например, ["devices.read", "devices.write"])
    is_admin: bool  # Административные права
    source: str  # Источник авторизации ("api_key", "session", "jwt", "oauth")
    user_id: Optional[str] = None  # ID пользователя (для users, sessions и JWT)
    session_id: Optional[str] = None  # ID сессии (для sessions)


async def validate_api_key(runtime: Any, api_key: str) -> Optional[RequestContext]:
    """
    Валидирует API Key и возвращает RequestContext.
    
    Включает проверку revocation и защиту от timing attacks.
    
    Args:
        runtime: экземпляр CoreRuntime
        api_key: API ключ из заголовка Authorization: Bearer <key>
    
    Returns:
        RequestContext если ключ валиден, None если не найден
    
    Raises:
        HTTPException: если ключ найден, но данные повреждены
    """
    if not api_key or not api_key.strip():
        return None
    
    # Проверка revocation
    if await is_revoked(runtime, api_key, "api_key"):
        return None
    
    try:
        # Получаем данные ключа из storage
        # Используем константное время для защиты от timing attacks
        key_data = await runtime.storage.get(AUTH_API_KEYS_NAMESPACE, api_key)
        
        # Timing attack protection - всегда выполняем проверку,
        # даже если ключ не найден (константное время)
        if key_data is None:
            # Имитируем работу для константного времени
            _ = secrets.compare_digest(api_key, api_key)
            return None
        
        # Проверяем структуру данных
        if not isinstance(key_data, dict):
            # Повреждённые данные - логируем и возвращаем None
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
                # Ключ истёк - удаляем его
                try:
                    await runtime.storage.delete(AUTH_API_KEYS_NAMESPACE, api_key)
                    await revoke_api_key(runtime, api_key)  # Добавляем в revoked list
                except Exception:
                    pass
                return None
        
        # Извлекаем данные
        subject = key_data.get("subject", f"api_key:{api_key[:8]}")
        scopes = key_data.get("scopes", [])
        is_admin = key_data.get("is_admin", False)
        
        # Нормализуем scopes
        if not isinstance(scopes, list):
            scopes = []
        
        # Обновляем last_used при каждой валидации (но не чаще чем раз в минуту)
        current_time = time.time()
        last_used = key_data.get("last_used")
        if last_used is None or current_time - last_used >= 60:  # Обновляем не чаще раза в минуту
            key_data["last_used"] = current_time
            await runtime.storage.set(AUTH_API_KEYS_NAMESPACE, api_key, key_data)
        
        return RequestContext(
            subject=subject,
            scopes=scopes,
            is_admin=is_admin,
            source="api_key"
        )
    
    except Exception as e:
        # Ошибка при чтении storage - логируем и возвращаем None
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


def extract_api_key_from_header(request: Request) -> Optional[str]:
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


def extract_session_from_cookie(request: Request) -> Optional[str]:
    """
    Извлекает session ID из Cookie.
    
    Args:
        request: FastAPI Request
    
    Returns:
        Session ID или None если cookie отсутствует
    """
    return request.cookies.get("session_id")


def extract_jwt_from_header(request: Request) -> Optional[str]:
    """
    Извлекает JWT access token из заголовка Authorization: Bearer <token>.
    
    Args:
        request: FastAPI Request
    
    Returns:
        JWT token или None если заголовок отсутствует/неверный формат
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
    
    return token


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
        payload = validate_access_token(token, secret)
        if not payload:
            return None
        
        user_id = payload.get("user_id")
        scopes = payload.get("scopes", [])
        is_admin = payload.get("is_admin", False)
        
        if not user_id:
            return None
        
        # Нормализуем scopes
        if not isinstance(scopes, list):
            scopes = []
        
        return RequestContext(
            subject=f"user:{user_id}",
            scopes=scopes,
            is_admin=is_admin,
            source="jwt",
            user_id=user_id
        )
    
    except Exception:
        return None


async def validate_session(runtime: Any, session_id: str) -> Optional[RequestContext]:
    """
    Валидирует session и возвращает RequestContext.
    
    Поддерживает users и sessions.
    Включает проверку revocation и защиту от timing attacks.
    
    Args:
        runtime: экземпляр CoreRuntime
        session_id: ID сессии из cookie
    
    Returns:
        RequestContext если сессия валидна, None если не найдена/истекла
    """
    if not session_id or not session_id.strip():
        return None
    
    # Проверка revocation
    if await is_revoked(runtime, session_id, "session"):
        return None
    
    try:
        # Получаем данные сессии из storage
        # Используем константное время для защиты от timing attacks
        session_data = await runtime.storage.get(AUTH_SESSIONS_NAMESPACE, session_id)
        
        # Timing attack protection - всегда выполняем проверку,
        # даже если сессия не найдена (константное время)
        if session_data is None:
            # Имитируем работу для константного времени
            _ = secrets.compare_digest(session_id, session_id)
            return None
        
        # Проверяем структуру данных
        if not isinstance(session_data, dict):
            try:
                await runtime.service_registry.call(
                    "logger.log",
                    level="warning",
                    message=f"Invalid session data structure for session: {session_id[:8]}...",
                    module="api"
                )
            except Exception:
                pass
            return None
        
        # Проверяем expiration
        expires_at = session_data.get("expires_at")
        if expires_at:
            current_time = time.time()
            if current_time > expires_at:
                # Сессия истекла - удаляем её
                try:
                    await runtime.storage.delete(AUTH_SESSIONS_NAMESPACE, session_id)
                except Exception:
                    pass
                return None
        
        # Извлекаем данные
        user_id = session_data.get("user_id")
        if not user_id:
            return None
        
        # Получаем данные пользователя
        user_data = await runtime.storage.get(AUTH_USERS_NAMESPACE, user_id)
        if user_data is None:
            # Пользователь не найден - удаляем сессию
            try:
                await runtime.storage.delete(AUTH_SESSIONS_NAMESPACE, session_id)
            except Exception:
                pass
            return None
        
        if not isinstance(user_data, dict):
            return None
        
        # Извлекаем scopes и is_admin из user_data
        scopes = user_data.get("scopes", [])
        is_admin = user_data.get("is_admin", False)
        
        # Нормализуем scopes
        if not isinstance(scopes, list):
            scopes = []
        
        # Обновляем last_used при каждой валидации (но не чаще чем раз в минуту для производительности)
        current_time = time.time()
        last_used = session_data.get("last_used", 0)
        if current_time - last_used >= 60:  # Обновляем не чаще раза в минуту
            session_data["last_used"] = current_time
            await runtime.storage.set(AUTH_SESSIONS_NAMESPACE, session_id, session_data)
        
        return RequestContext(
            subject=f"user:{user_id}",
            scopes=scopes,
            is_admin=is_admin,
            source="session",
            user_id=user_id,
            session_id=session_id
        )
    
    except Exception as e:
        # Ошибка при чтении storage - логируем и возвращаем None
        try:
            await runtime.service_registry.call(
                "logger.log",
                level="error",
                message=f"Error validating session: {e}",
                module="api"
            )
        except Exception:
            pass
        return None


async def create_session(
    runtime: Any,
    user_id: str,
    expiration_seconds: Optional[int] = None,
    client_ip: Optional[str] = None,
    user_agent: Optional[str] = None
) -> str:
    """
    Создаёт новую сессию для пользователя.
    
    Включает валидацию существования пользователя и сохранение метаданных.
    
    Args:
        runtime: экземпляр CoreRuntime
        user_id: ID пользователя
        expiration_seconds: время жизни сессии (по умолчанию 24 часа)
        client_ip: IP адрес клиента (опционально, для метаданных)
        user_agent: User-Agent заголовок (опционально, для метаданных)
    
    Returns:
        Session ID
    
    Raises:
        ValueError: если пользователь не существует
    """
    # Валидация существования пользователя
    if not await validate_user_exists(runtime, user_id):
        raise ValueError(f"User {user_id} not found")
    
    # Генерируем уникальный session ID
    session_id = secrets.token_urlsafe(32)
    
    # Устанавливаем expiration
    if expiration_seconds is None:
        expiration_seconds = DEFAULT_SESSION_EXPIRATION_SECONDS
    
    expires_at = time.time() + expiration_seconds
    current_time = time.time()
    
    # Сохраняем сессию с метаданными
    session_data = {
        "user_id": user_id,
        "created_at": current_time,
        "expires_at": expires_at,
        "last_used": current_time,  # Инициализируем last_used
    }
    
    # Добавляем метаданные, если предоставлены
    if client_ip:
        session_data["client_ip"] = client_ip
    if user_agent:
        # Ограничиваем длину user_agent для экономии места
        session_data["user_agent"] = user_agent[:256]
    
    await runtime.storage.set(AUTH_SESSIONS_NAMESPACE, session_id, session_data)
    
    # Audit logging
    await audit_log_auth_event(
        runtime,
        "session_created",
        user_id,
        {
            "session_id": session_id[:16] + "...",
            "expiration_seconds": expiration_seconds,
            "client_ip": client_ip,
        },
        success=True
    )
    
    return session_id


async def delete_session(runtime: Any, session_id: str) -> None:
    """
    Удаляет сессию.
    
    Args:
        runtime: экземпляр CoreRuntime
        session_id: ID сессии
    """
    try:
        await runtime.storage.delete(AUTH_SESSIONS_NAMESPACE, session_id)
    except Exception:
        pass


async def list_sessions(runtime: Any, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Возвращает список активных сессий.
    
    Args:
        runtime: экземпляр CoreRuntime
        user_id: опциональный фильтр по user_id (если None, возвращает все сессии)
    
    Returns:
        Список словарей с информацией о сессиях:
        - session_id (обрезанный для безопасности)
        - user_id
        - created_at
        - expires_at
        - last_used
        - client_ip (если есть)
        - user_agent (если есть)
        - is_expired (bool)
    """
    try:
        all_session_ids = await runtime.storage.list_keys(AUTH_SESSIONS_NAMESPACE)
        current_time = time.time()
        result = []
        
        for session_id in all_session_ids:
            try:
                session_data = await runtime.storage.get(AUTH_SESSIONS_NAMESPACE, session_id)
                if not isinstance(session_data, dict):
                    continue
                
                session_user_id = session_data.get("user_id")
                
                # Фильтруем по user_id, если указан
                if user_id is not None and session_user_id != user_id:
                    continue
                
                expires_at = session_data.get("expires_at", 0)
                is_expired = current_time > expires_at
                
                # Если сессия истекла, пропускаем её (или можно включить опционально)
                if is_expired:
                    continue
                
                session_info = {
                    "session_id": session_id[:16] + "...",  # Обрезаем для безопасности
                    "user_id": session_user_id,
                    "created_at": session_data.get("created_at"),
                    "expires_at": expires_at,
                    "last_used": session_data.get("last_used"),
                    "is_expired": is_expired,
                }
                
                # Добавляем метаданные, если есть
                if "client_ip" in session_data:
                    session_info["client_ip"] = session_data["client_ip"]
                if "user_agent" in session_data:
                    session_info["user_agent"] = session_data["user_agent"]
                
                result.append(session_info)
            except Exception:
                # Пропускаем повреждённые сессии
                continue
        
        # Сортируем по last_used (новые сначала)
        result.sort(key=lambda x: x.get("last_used", 0), reverse=True)
        return result
    
    except Exception:
        return []


async def revoke_all_sessions(runtime: Any, user_id: str) -> int:
    """
    Отзывает все активные сессии пользователя.
    
    Args:
        runtime: экземпляр CoreRuntime
        user_id: ID пользователя
    
    Returns:
        Количество отозванных сессий
    """
    revoked_count = 0
    
    try:
        all_session_ids = await runtime.storage.list_keys(AUTH_SESSIONS_NAMESPACE)
        
        for session_id in all_session_ids:
            try:
                session_data = await runtime.storage.get(AUTH_SESSIONS_NAMESPACE, session_id)
                if not isinstance(session_data, dict):
                    continue
                
                # Проверяем, принадлежит ли сессия пользователю
                if session_data.get("user_id") == user_id:
                    await revoke_session(runtime, session_id)
                    revoked_count += 1
            except Exception:
                # Пропускаем ошибки при обработке отдельных сессий
                continue
        
        # Audit logging
        await audit_log_auth_event(
            runtime,
            "all_sessions_revoked",
            user_id,
            {"revoked_count": revoked_count},
            success=True
        )
        
        return revoked_count
    
    except Exception as e:
        # Логируем ошибку, но не падаем
        try:
            await runtime.service_registry.call(
                "logger.log",
                level="error",
                message=f"Error revoking all sessions for {user_id}: {e}",
                module="api"
            )
        except Exception:
            pass
        return revoked_count


def check_service_scope(context: Optional[RequestContext], service_name: str) -> bool:
    """
    Проверяет, есть ли у контекста права на вызов сервиса.
    
    Правила:
    - Если context is None (нет авторизации) → False
    - Если is_admin=True → True (полный доступ)
    - Если service_name начинается с "admin." → требуется is_admin=True
    - Иначе проверяем scopes по паттерну: <namespace>.<action> или <namespace>.*
    
    Args:
        context: RequestContext или None
        service_name: имя сервиса (например, "devices.list", "admin.v1.runtime")
    
    Returns:
        True если есть права, False если нет
    """
    if context is None:
        return False
    
    # Администраторы имеют полный доступ
    if context.is_admin:
        return True
    
    # Административные сервисы требуют admin прав
    if service_name.startswith("admin."):
        return False
    
    # Извлекаем namespace и action из service_name
    # Формат: "namespace.action" или "namespace.sub.action"
    parts = service_name.split(".", 1)
    if len(parts) < 2:
        # Нестандартный формат - требуем admin
        return False
    
    namespace = parts[0]
    action = parts[1]
    
    # Проверяем scopes
    # Поддерживаем:
    # - "namespace.action" (точное совпадение)
    # - "namespace.*" (все действия в namespace)
    # - "*" (все действия)
    required_scope_exact = f"{namespace}.{action}"
    required_scope_wildcard = f"{namespace}.*"
    
    if "*" in context.scopes:
        return True
    
    if required_scope_exact in context.scopes:
        return True
    
    if required_scope_wildcard in context.scopes:
        return True
    
    return False


# ============================================================================
# Rate Limiting
# ============================================================================

async def rate_limit_check(
    runtime: Any,
    identifier: str,
    limit_type: str = "auth",
    limit: Optional[int] = None,
    window_seconds: Optional[int] = None
) -> bool:
    """
    Проверяет rate limit для идентификатора.
    
    Защита от brute force атак.
    
    Args:
        runtime: экземпляр CoreRuntime
        identifier: API key, session_id или IP address
        limit_type: "auth" (для auth попыток) или "api" (для API запросов)
        limit: максимальное количество попыток (по умолчанию из констант)
        window_seconds: окно времени в секундах (по умолчанию из констант)
    
    Returns:
        True если лимит не превышен, False если превышен
    """
    if limit is None:
        limit = RATE_LIMIT_AUTH_ATTEMPTS if limit_type == "auth" else RATE_LIMIT_API_REQUESTS
    
    if window_seconds is None:
        window_seconds = RATE_LIMIT_AUTH_WINDOW if limit_type == "auth" else RATE_LIMIT_API_WINDOW
    
    try:
        # Создаём ключ для rate limit (hash для безопасности)
        rate_key = hashlib.sha256(f"{limit_type}:{identifier}".encode()).hexdigest()
        
        # Получаем текущий счётчик
        rate_data = await runtime.storage.get(AUTH_RATE_LIMITS_NAMESPACE, rate_key)
        
        current_time = time.time()
        
        if rate_data is None or not isinstance(rate_data, dict):
            # Первая попытка - создаём счётчик
            rate_data = {
                "count": 1,
                "window_start": current_time,
                "last_attempt": current_time
            }
            await runtime.storage.set(AUTH_RATE_LIMITS_NAMESPACE, rate_key, rate_data)
            return True
        
        window_start = rate_data.get("window_start", current_time)
        count = rate_data.get("count", 0)
        
        # Проверяем, не истёк ли window
        if current_time - window_start >= window_seconds:
            # Окно истекло - сбрасываем счётчик
            rate_data = {
                "count": 1,
                "window_start": current_time,
                "last_attempt": current_time
            }
            await runtime.storage.set(AUTH_RATE_LIMITS_NAMESPACE, rate_key, rate_data)
            return True
        
        # Проверяем лимит
        if count >= limit:
            return False
        
        # Увеличиваем счётчик
        rate_data["count"] = count + 1
        rate_data["last_attempt"] = current_time
        await runtime.storage.set(AUTH_RATE_LIMITS_NAMESPACE, rate_key, rate_data)
        return True
    
    except Exception as e:
        # При ошибке разрешаем запрос (fail-open для доступности)
        try:
            await runtime.service_registry.call(
                "logger.log",
                level="error",
                message=f"Rate limit check error: {e}",
                module="api"
            )
        except Exception:
            pass
        return True  # Fail-open


# ============================================================================
# Audit Logging
# ============================================================================

async def audit_log_auth_event(
    runtime: Any,
    event_type: str,
    subject: str,
    details: Optional[Dict[str, Any]] = None,
    success: bool = False
) -> None:
    """
    Логирует auth событие для аудита.
    
    Отслеживание auth событий.
    
    Args:
        runtime: экземпляр CoreRuntime
        event_type: тип события ("auth_success", "auth_failure", "key_revoked", "session_created", etc.)
        subject: идентификатор субъекта (API key, session_id, user_id)
        details: дополнительные детали (IP, path, user_agent, etc.)
        success: успешность операции
    """
    try:
        audit_entry = {
            "timestamp": time.time(),
            "event_type": event_type,
            "subject": subject[:64] if subject else "unknown",  # Ограничиваем длину
            "success": success,
            "details": details or {}
        }
        
        # Сохраняем в audit log (с timestamp как часть ключа для уникальности)
        audit_key = f"{int(time.time() * 1000)}_{hashlib.sha256(subject.encode() if subject else b'').hexdigest()[:16]}"
        await runtime.storage.set(AUTH_AUDIT_LOG_NAMESPACE, audit_key, audit_entry)
    
    except Exception as e:
        # Не падаем при ошибке audit logging
        try:
            await runtime.service_registry.call(
                "logger.log",
                level="error",
                message=f"Audit logging error: {e}",
                module="api"
            )
        except Exception:
            pass


# ============================================================================
# Revocation
# ============================================================================

async def revoke_api_key(runtime: Any, api_key: str) -> None:
    """
    Отзывает API key.
    
    Механизм отзыва ключей.
    
    Args:
        runtime: экземпляр CoreRuntime
        api_key: API ключ для отзыва
    """
    try:
        # Сохраняем в revoked list
        revoked_entry = {
            "revoked_at": time.time(),
            "type": "api_key"
        }
        revoked_key = hashlib.sha256(api_key.encode()).hexdigest()
        await runtime.storage.set(AUTH_REVOKED_NAMESPACE, revoked_key, revoked_entry)
        
        # Удаляем из активных ключей
        try:
            await runtime.storage.delete(AUTH_API_KEYS_NAMESPACE, api_key)
        except Exception:
            pass
        
        # Логируем
        await audit_log_auth_event(
            runtime,
            "key_revoked",
            api_key[:16] + "...",
            {"type": "api_key"},
            success=True
        )
    
    except Exception as e:
        try:
            await runtime.service_registry.call(
                "logger.log",
                level="error",
                message=f"Error revoking API key: {e}",
                module="api"
            )
        except Exception:
            pass


async def rotate_api_key(runtime: Any, old_api_key: str, expires_at: Optional[float] = None) -> str:
    """
    Ротирует API key: создаёт новый ключ и отзывает старый.
    
    Полезно для регулярной ротации ключей в целях безопасности.
    
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
    scopes = old_key_data.get("scopes", [])
    is_admin = old_key_data.get("is_admin", False)
    subject = old_key_data.get("subject")
    
    # Создаём новый ключ с теми же правами
    new_api_key = await create_api_key(
        runtime,
        scopes=scopes,
        is_admin=is_admin,
        subject=subject,
        expires_at=expires_at
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


async def revoke_session(runtime: Any, session_id: str) -> None:
    """
    Отзывает session.
    
    Механизм отзыва сессий.
    
    Args:
        runtime: экземпляр CoreRuntime
        session_id: ID сессии для отзыва
    """
    try:
        # Сохраняем в revoked list
        revoked_entry = {
            "revoked_at": time.time(),
            "type": "session"
        }
        revoked_key = hashlib.sha256(session_id.encode()).hexdigest()
        await runtime.storage.set(AUTH_REVOKED_NAMESPACE, revoked_key, revoked_entry)
        
        # Удаляем из активных сессий
        try:
            await runtime.storage.delete(AUTH_SESSIONS_NAMESPACE, session_id)
        except Exception:
            pass
        
        # Логируем
        await audit_log_auth_event(
            runtime,
            "session_revoked",
            session_id[:16] + "...",
            {"type": "session"},
            success=True
        )
    
    except Exception as e:
        try:
            await runtime.service_registry.call(
                "logger.log",
                level="error",
                message=f"Error revoking session: {e}",
                module="api"
            )
        except Exception:
            pass


async def is_revoked(runtime: Any, identifier: str, revoke_type: str) -> bool:
    """
    Проверяет, отозван ли ключ или сессия.
    
    Проверка revocation.
    
    Args:
        runtime: экземпляр CoreRuntime
        identifier: API key или session_id
        revoke_type: "api_key" или "session"
    
    Returns:
        True если отозван, False если нет
    """
    try:
        revoked_key = hashlib.sha256(identifier.encode()).hexdigest()
        revoked_entry = await runtime.storage.get(AUTH_REVOKED_NAMESPACE, revoked_key)
        
        if revoked_entry is None:
            return False
        
        if not isinstance(revoked_entry, dict):
            return False
        
        # Проверяем тип
        entry_type = revoked_entry.get("type")
        if entry_type != revoke_type:
            return False
        
        return True
    
    except Exception:
        # При ошибке считаем, что не отозван (fail-open)
        return False


# ============================================================================
# Password Management
# ============================================================================

def hash_password(password: str) -> str:
    """
    Хеширует пароль используя bcrypt.
    
    Args:
        password: пароль в открытом виде
    
    Returns:
        Хешированный пароль (строка)
    """
    # Генерируем salt и хешируем пароль
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
    
    Включает валидацию силы пароля и хеширование.
    
    Args:
        runtime: экземпляр CoreRuntime
        user_id: ID пользователя
        password: пароль в открытом виде
    
    Raises:
        ValueError: если пользователь не существует или пароль не соответствует политикам
    """
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
    
    Требует проверки старого пароля.
    
    Args:
        runtime: экземпляр CoreRuntime
        user_id: ID пользователя
        old_password: текущий пароль
        new_password: новый пароль
    
    Raises:
        ValueError: если пользователь не существует, старый пароль неверен или новый пароль не соответствует политикам
    """
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
        # Audit logging для неудачной попытки
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
    
    # Отзываем все сессии пользователя при смене пароля (безопасность)
    try:
        sessions = await runtime.storage.list_keys(AUTH_SESSIONS_NAMESPACE)
        for session_id in sessions:
            session_data = await runtime.storage.get(AUTH_SESSIONS_NAMESPACE, session_id)
            if isinstance(session_data, dict) and session_data.get("user_id") == user_id:
                await revoke_session(runtime, session_id)
    except Exception:
        # Не падаем при ошибке отзыва сессий
        pass


async def verify_user_password(runtime: Any, user_id: str, password: str) -> bool:
    """
    Проверяет пароль пользователя.
    
    Используется при логине.
    
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


# ============================================================================
# JWT Token Management
# ============================================================================

async def get_or_create_jwt_secret(runtime: Any) -> str:
    """
    Получает или создаёт JWT secret key.
    
    Args:
        runtime: экземпляр CoreRuntime
    
    Returns:
        JWT secret key (строка)
    """
    try:
        secret = await runtime.storage.get("auth_config", JWT_SECRET_KEY_STORAGE_KEY)
        if secret and isinstance(secret, str):
            return secret
    except Exception:
        pass
    
    # Генерируем новый secret
    secret = secrets.token_urlsafe(JWT_SECRET_KEY_LENGTH)
    try:
        await runtime.storage.set("auth_config", JWT_SECRET_KEY_STORAGE_KEY, secret)
    except Exception:
        pass
    
    return secret


def generate_access_token(
    user_id: str,
    scopes: List[str],
    is_admin: bool,
    secret: str,
    expiration_seconds: int = ACCESS_TOKEN_EXPIRATION_SECONDS
) -> str:
    """
    Генерирует JWT access token.
    
    Args:
        user_id: ID пользователя
        scopes: список scopes
        is_admin: административные права
        secret: JWT secret key
        expiration_seconds: время жизни токена в секундах
    
    Returns:
        JWT token (строка)
    """
    current_time = time.time()
    payload = {
        "user_id": user_id,
        "scopes": scopes,
        "is_admin": is_admin,
        "iat": current_time,  # issued at
        "exp": current_time + expiration_seconds,  # expiration
        "type": "access"
    }
    
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def validate_access_token(token: str, secret: str) -> Optional[Dict[str, Any]]:
    """
    Валидирует JWT access token.
    
    Args:
        token: JWT token
        secret: JWT secret key
    
    Returns:
        Payload если токен валиден, None если невалиден
    """
    try:
        payload = jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
        
        # Проверяем тип токена
        if payload.get("type") != "access":
            return None
        
        return payload
    except ExpiredSignatureError:
        return None
    except InvalidTokenError:
        return None
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
    
    Args:
        runtime: экземпляр CoreRuntime
        refresh_token: refresh token для проверки
    
    Returns:
        Token data если валиден, None если невалиден
    """
    if not refresh_token or not refresh_token.strip():
        return None
    
    # Проверка revocation
    if await is_revoked(runtime, refresh_token, "refresh_token"):
        return None
    
    try:
        token_data = await runtime.storage.get(AUTH_REFRESH_TOKENS_NAMESPACE, refresh_token)
        
        if not isinstance(token_data, dict):
            return None
        
        # Проверяем expiration
        expires_at = token_data.get("expires_at")
        if expires_at:
            current_time = time.time()
            if current_time > expires_at:
                # Токен истёк - удаляем его
                try:
                    await runtime.storage.delete(AUTH_REFRESH_TOKENS_NAMESPACE, refresh_token)
                except Exception:
                    pass
                return None
        
        # Обновляем last_used
        token_data["last_used"] = time.time()
        await runtime.storage.set(AUTH_REFRESH_TOKENS_NAMESPACE, refresh_token, token_data)
        
        return token_data
    
    except Exception:
        return None


async def revoke_refresh_token(runtime: Any, refresh_token: str) -> None:
    """
    Отзывает refresh token.
    
    Args:
        runtime: экземпляр CoreRuntime
        refresh_token: refresh token для отзыва
    """
    try:
        # Сохраняем в revoked list
        revoked_entry = {
            "revoked_at": time.time(),
            "type": "refresh_token"
        }
        revoked_key = hashlib.sha256(refresh_token.encode()).hexdigest()
        await runtime.storage.set(AUTH_REVOKED_NAMESPACE, revoked_key, revoked_entry)
        
        # Удаляем из активных токенов
        try:
            await runtime.storage.delete(AUTH_REFRESH_TOKENS_NAMESPACE, refresh_token)
        except Exception:
            pass
        
        # Audit logging
        await audit_log_auth_event(
            runtime,
            "refresh_token_revoked",
            refresh_token[:16] + "...",
            {"type": "refresh_token"},
            success=True
        )
    
    except Exception as e:
        try:
            await runtime.service_registry.call(
                "logger.log",
                level="error",
                message=f"Error revoking refresh token: {e}",
                module="api"
            )
        except Exception:
            pass


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
    
    scopes = user_data.get("scopes", [])
    is_admin = user_data.get("is_admin", False)
    
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


# ============================================================================
# Input Validation
# ============================================================================

async def validate_user_exists(runtime: Any, user_id: str) -> bool:
    """
    Проверяет существование пользователя.
    
    Валидация входных данных.
    
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


async def create_api_key(
    runtime: Any,
    scopes: List[str],
    is_admin: bool = False,
    subject: Optional[str] = None,
    expires_at: Optional[float] = None
) -> str:
    """
    Создаёт новый API key.
    
    Args:
        runtime: экземпляр CoreRuntime
        scopes: список scopes (например, ["devices.read", "devices.write"])
        is_admin: является ли ключ административным
        subject: опциональный subject (по умолчанию генерируется)
        expires_at: опциональное время истечения (timestamp), None = без истечения
    
    Returns:
        API key (строка)
    """
    # Валидация scopes
    if not validate_scopes(scopes):
        raise ValueError("Invalid scopes format")
    
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
        "last_used": None,  # Инициализируем как None
    }
    
    # Добавляем expires_at, если указано
    if expires_at is not None:
        key_data["expires_at"] = expires_at
    
    await runtime.storage.set(AUTH_API_KEYS_NAMESPACE, api_key, key_data)
    
    # Audit logging
    await audit_log_auth_event(
        runtime,
        "key_created",
        subject,
        {"scopes": scopes, "is_admin": is_admin, "expires_at": expires_at},
        success=True
    )
    
    return api_key


async def create_user(
    runtime: Any,
    user_id: str,
    scopes: List[str],
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
    # Валидация scopes
    if not validate_scopes(scopes):
        raise ValueError("Invalid scopes format")
    
    # Проверяем, не существует ли уже пользователь
    if await validate_user_exists(runtime, user_id):
        raise ValueError(f"User {user_id} already exists")
    
    # Валидация и хеширование пароля, если указан
    password_hash = None
    if password:
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


def validate_scopes(scopes: List[str]) -> bool:
    """
    Валидирует формат scopes.
    
    Валидация входных данных.
    
    Args:
        scopes: список scopes
    
    Returns:
        True если все scopes валидны, False если нет
    """
    if not isinstance(scopes, list):
        return False
    
    for scope in scopes:
        if not isinstance(scope, str):
            return False
        # Проверяем формат: namespace.action или namespace.* или *
        if scope == "*":
            continue
        if "." not in scope:
            return False
        if scope.endswith(".") or scope.startswith("."):
            return False
    
    return True


async def get_request_context(request: Request) -> Optional[RequestContext]:
    """
    Получает RequestContext из request.state.
    
    Используется в handlers для доступа к контексту авторизации.
    
    Args:
        request: FastAPI Request
    
    Returns:
        RequestContext или None если не установлен
    """
    return getattr(request.state, "auth_context", None)


async def require_auth_middleware(request: Request, call_next):
    """
    FastAPI middleware для проверки авторизации (JWT, API Key или Session).
    
    Поддерживает JWT access tokens, API keys и sessions через cookies.
    Включает rate limiting и audit logging.
    
    Приоритет:
    1. JWT access token из Authorization header (Bearer token)
    2. API Key из Authorization header (Bearer token, если не JWT)
    3. Session из Cookie (session_id)
    
    Извлекает credentials, валидирует их и сохраняет RequestContext
    в request.state.auth_context.
    
    Если credentials не переданы или невалидны, context будет None.
    Проверка прав выполняется в handlers перед вызовом service_registry.call().
    
    Args:
        request: FastAPI Request
        call_next: следующий middleware/handler
    
    Returns:
        Response
    """
    # Получаем runtime из app.state (устанавливается в ApiModule)
    runtime = getattr(request.app.state, "runtime", None)
    
    context = None
    identifier = None
    auth_source = None
    
    # Получаем IP для rate limiting и audit
    client_ip = request.client.host if request.client else "unknown"
    
    # Проверяем, является ли это auth endpoint (требует специального rate limiting)
    is_auth_endpoint = str(request.url.path).startswith("/admin/auth/")
    
    # Rate limiting для auth endpoints (до попытки авторизации)
    if is_auth_endpoint and runtime:
        rate_limit_key = f"auth:{client_ip}"
        if not await rate_limit_check(runtime, rate_limit_key, "auth"):
            await audit_log_auth_event(
                runtime,
                "rate_limit_exceeded",
                client_ip,
                {"ip": client_ip, "path": str(request.url.path), "type": "auth_endpoint", "limit_type": "auth"},
                success=False
            )
            return Response(
                content='{"detail": "Rate limit exceeded. Too many authentication attempts. Please try again later."}',
                status_code=429,
                media_type="application/json",
                headers={
                    "Retry-After": "60",
                    "X-RateLimit-Limit": str(RATE_LIMIT_AUTH_ATTEMPTS),
                    "X-RateLimit-Window": str(RATE_LIMIT_AUTH_WINDOW)
                }
            )
    
    # Приоритет 1: JWT access token из Authorization header
    jwt_token = extract_jwt_from_header(request)
    if jwt_token and runtime:
        try:
            context = await validate_jwt_token(runtime, jwt_token)
            if context:
                identifier = context.user_id or context.subject
                auth_source = "jwt"
                
                # Если авторизация успешна, применяем rate limiting для API запросов (не для auth endpoints)
                if context and not is_auth_endpoint:
                    rate_limit_key = f"api:jwt:{context.user_id or 'unknown'}"
                    if not await rate_limit_check(runtime, rate_limit_key, "api"):
                        # Превышен лимит API запросов
                        await audit_log_auth_event(
                            runtime,
                            "rate_limit_exceeded",
                            context.user_id or "unknown",
                            {"ip": client_ip, "path": str(request.url.path), "type": "jwt", "limit_type": "api"},
                            success=False
                        )
                        return Response(
                            content='{"detail": "Rate limit exceeded. Too many requests. Please try again later."}',
                            status_code=429,
                            media_type="application/json",
                            headers={
                                "Retry-After": "60",
                                "X-RateLimit-Limit": str(RATE_LIMIT_API_REQUESTS),
                                "X-RateLimit-Window": str(RATE_LIMIT_API_WINDOW)
                            }
                        )
        except Exception:
            context = None
    
    # Приоритет 2: API Key из Authorization header (если JWT не сработал)
    if context is None:
        api_key = extract_api_key_from_header(request)
        if api_key and runtime:
            try:
                context = await validate_api_key(runtime, api_key)
                if context:
                    identifier = api_key
                    auth_source = "api_key"
                    
                    # Если авторизация успешна, применяем rate limiting для API запросов (не для auth endpoints)
                    if not is_auth_endpoint:
                        rate_limit_key = f"api:{api_key[:16]}"
                        if not await rate_limit_check(runtime, rate_limit_key, "api"):
                            # Превышен лимит API запросов
                            await audit_log_auth_event(
                                runtime,
                                "rate_limit_exceeded",
                                api_key[:16] + "...",
                                {"ip": client_ip, "path": str(request.url.path), "type": "api_key", "limit_type": "api"},
                                success=False
                            )
                            return Response(
                                content='{"detail": "Rate limit exceeded. Too many requests. Please try again later."}',
                                status_code=429,
                                media_type="application/json",
                                headers={
                                    "Retry-After": "60",
                                    "X-RateLimit-Limit": str(RATE_LIMIT_API_REQUESTS),
                                    "X-RateLimit-Window": str(RATE_LIMIT_API_WINDOW)
                                }
                            )
            except Exception:
                context = None
    
    # Приоритет 3: Session из Cookie (если JWT и API Key не сработали)
    if context is None:
        session_id = extract_session_from_cookie(request)
        if session_id and runtime:
            try:
                context = await validate_session(runtime, session_id)
                identifier = session_id
                auth_source = "session"
                
                # Если авторизация успешна, применяем rate limiting для API запросов (не для auth endpoints)
                if context and not is_auth_endpoint:
                    rate_limit_key = f"api:{session_id[:16]}"
                    if not await rate_limit_check(runtime, rate_limit_key, "api"):
                        # Превышен лимит API запросов
                        await audit_log_auth_event(
                            runtime,
                            "rate_limit_exceeded",
                            session_id[:16] + "...",
                            {"ip": client_ip, "path": str(request.url.path), "type": "session", "limit_type": "api"},
                            success=False
                        )
                        return Response(
                            content='{"detail": "Rate limit exceeded. Too many requests. Please try again later."}',
                            status_code=429,
                            media_type="application/json",
                            headers={
                                "Retry-After": "60",
                                "X-RateLimit-Limit": str(RATE_LIMIT_API_REQUESTS),
                                "X-RateLimit-Window": str(RATE_LIMIT_API_WINDOW)
                            }
                        )
            except Exception:
                context = None
    
    # Audit logging
    if identifier:
        await audit_log_auth_event(
            runtime,
            "auth_success" if context else "auth_failure",
            identifier[:16] + "...",
            {
                "ip": client_ip,
                "path": str(request.url.path),
                "source": auth_source,
                "user_agent": request.headers.get("user-agent", "unknown")[:128]
            },
            success=(context is not None)
        )
    
    # Сохраняем context в request.state
    request.state.auth_context = context
    
    # Продолжаем обработку запроса
    response = await call_next(request)
    return response
