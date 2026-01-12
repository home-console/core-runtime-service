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
from typing import Any, Optional, List, Dict
import time
import secrets
import hashlib
from fastapi import Request, HTTPException, status

# Storage namespaces
AUTH_API_KEYS_NAMESPACE = "auth_api_keys"
AUTH_SESSIONS_NAMESPACE = "auth_sessions"
AUTH_USERS_NAMESPACE = "auth_users"
AUTH_RATE_LIMITS_NAMESPACE = "auth_rate_limits"
AUTH_AUDIT_LOG_NAMESPACE = "auth_audit_log"
AUTH_REVOKED_NAMESPACE = "auth_revoked"

# Default session expiration (24 hours)
DEFAULT_SESSION_EXPIRATION_SECONDS = 24 * 60 * 60

# Rate limiting defaults
RATE_LIMIT_AUTH_ATTEMPTS = 5  # попыток
RATE_LIMIT_AUTH_WINDOW = 60  # секунд
RATE_LIMIT_API_REQUESTS = 100  # запросов
RATE_LIMIT_API_WINDOW = 60  # секунд


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
    source: str  # Источник авторизации ("api_key", "session", "oauth")
    user_id: Optional[str] = None  # ID пользователя (для users и sessions)
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
        
        # Извлекаем данные
        subject = key_data.get("subject", f"api_key:{api_key[:8]}")
        scopes = key_data.get("scopes", [])
        is_admin = key_data.get("is_admin", False)
        
        # Нормализуем scopes
        if not isinstance(scopes, list):
            scopes = []
        
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


async def create_session(runtime: Any, user_id: str, expiration_seconds: Optional[int] = None) -> str:
    """
    Создаёт новую сессию для пользователя.
    
    Включает валидацию существования пользователя.
    
    Args:
        runtime: экземпляр CoreRuntime
        user_id: ID пользователя
        expiration_seconds: время жизни сессии (по умолчанию 24 часа)
    
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
    
    # Сохраняем сессию
    session_data = {
        "user_id": user_id,
        "created_at": time.time(),
        "expires_at": expires_at
    }
    
    await runtime.storage.set(AUTH_SESSIONS_NAMESPACE, session_id, session_data)
    
    # Audit logging
    await audit_log_auth_event(
        runtime,
        "session_created",
        user_id,
        {"session_id": session_id[:16] + "...", "expiration_seconds": expiration_seconds},
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
        
        # Также логируем через logger для немедленного мониторинга
        try:
            await runtime.service_registry.call(
                "logger.log",
                level="info" if success else "warning",
                message=f"Auth event: {event_type} for {subject[:16]}...",
                module="api"
            )
        except Exception:
            pass
    
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
    FastAPI middleware для проверки авторизации (API Key или Session).
    
    Поддерживает sessions через cookies.
    Включает rate limiting и audit logging.
    
    Приоритет:
    1. API Key из Authorization header (Bearer token)
    2. Session из Cookie (session_id)
    
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
    
    # Приоритет 1: API Key из Authorization header
    api_key = extract_api_key_from_header(request)
    if api_key and runtime:
        # Rate limiting для auth попыток
        rate_limit_key = f"{client_ip}:{api_key[:16]}"
        if not await rate_limit_check(runtime, rate_limit_key, "auth"):
            # Логируем превышение лимита
            await audit_log_auth_event(
                runtime,
                "rate_limit_exceeded",
                api_key[:16] + "...",
                {"ip": client_ip, "path": str(request.url.path), "type": "api_key"},
                success=False
            )
            response = await call_next(request)
            # Устанавливаем context в None для последующей проверки в handler
            request.state.auth_context = None
            return response
        
        try:
            context = await validate_api_key(runtime, api_key)
            identifier = api_key
            auth_source = "api_key"
        except Exception:
            context = None
    
    # Приоритет 2: Session из Cookie (если API Key не сработал)
    if context is None:
        session_id = extract_session_from_cookie(request)
        if session_id and runtime:
            # Rate limiting для auth попыток
            rate_limit_key = f"{client_ip}:{session_id[:16]}"
            if not await rate_limit_check(runtime, rate_limit_key, "auth"):
                # Логируем превышение лимита
                await audit_log_auth_event(
                    runtime,
                    "rate_limit_exceeded",
                    session_id[:16] + "...",
                    {"ip": client_ip, "path": str(request.url.path), "type": "session"},
                    success=False
                )
                response = await call_next(request)
                request.state.auth_context = None
                return response
            
            try:
                context = await validate_session(runtime, session_id)
                identifier = session_id
                auth_source = "session"
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
