"""
API Key Authentication — boundary-layer для ApiModule и AdminModule.

Это boundary-layer: auth логика НЕ проникает в CoreRuntime, RuntimeModule,
ServiceRegistry или доменные модули. Всё изолировано на уровне HTTP.

Архитектура:
- RequestContext передаётся через request.state (FastAPI)
- validate_api_key() проверяет ключ и возвращает RequestContext
- validate_session() проверяет сессию и возвращает RequestContext (Stage B)
- check_service_scope() проверяет права на вызов сервиса
- API keys хранятся в runtime.storage namespace "auth_api_keys"
- Sessions хранятся в runtime.storage namespace "auth_sessions"
- Users хранятся в runtime.storage namespace "auth_users"

Stage B:
- Поддержка users и sessions
- Cookie-based authentication
- Session expiration
"""

from dataclasses import dataclass
from typing import Any, Optional, List, Dict
import time
from fastapi import Request, HTTPException, status

# Storage namespaces
AUTH_API_KEYS_NAMESPACE = "auth_api_keys"
AUTH_SESSIONS_NAMESPACE = "auth_sessions"
AUTH_USERS_NAMESPACE = "auth_users"

# Default session expiration (24 hours)
DEFAULT_SESSION_EXPIRATION_SECONDS = 24 * 60 * 60


@dataclass
class RequestContext:
    """
    Контекст авторизации для HTTP запроса.
    
    Передаётся через request.state в FastAPI.
    Не проникает в CoreRuntime или доменные модули.
    
    Stage B: расширен для поддержки users и sessions.
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
    
    try:
        # Получаем данные ключа из storage
        key_data = await runtime.storage.get(AUTH_API_KEYS_NAMESPACE, api_key)
        
        if key_data is None:
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
    
    Stage B: поддержка users и sessions.
    
    Args:
        runtime: экземпляр CoreRuntime
        session_id: ID сессии из cookie
    
    Returns:
        RequestContext если сессия валидна, None если не найдена/истекла
    """
    if not session_id or not session_id.strip():
        return None
    
    try:
        # Получаем данные сессии из storage
        session_data = await runtime.storage.get(AUTH_SESSIONS_NAMESPACE, session_id)
        
        if session_data is None:
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
    
    Stage B: создание сессий для users.
    
    Args:
        runtime: экземпляр CoreRuntime
        user_id: ID пользователя
        expiration_seconds: время жизни сессии (по умолчанию 24 часа)
    
    Returns:
        Session ID
    """
    import secrets
    
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
    
    Stage B: поддержка sessions через cookies.
    
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
    
    # Приоритет 1: API Key из Authorization header
    api_key = extract_api_key_from_header(request)
    if api_key and runtime:
        try:
            context = await validate_api_key(runtime, api_key)
        except Exception:
            context = None
    
    # Приоритет 2: Session из Cookie (если API Key не сработал)
    if context is None:
        session_id = extract_session_from_cookie(request)
        if session_id and runtime:
            try:
                context = await validate_session(runtime, session_id)
            except Exception:
                context = None
    
    # Сохраняем context в request.state
    request.state.auth_context = context
    
    # Продолжаем обработку запроса
    response = await call_next(request)
    return response
