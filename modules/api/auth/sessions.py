"""
Session management — создание, валидация, управление и отзыв сессий.
"""

from typing import Any, Optional, List, Dict
import time
import secrets
from fastapi import Request

from .context import RequestContext
from .constants import AUTH_SESSIONS_NAMESPACE, AUTH_USERS_NAMESPACE, DEFAULT_SESSION_EXPIRATION_SECONDS
from .revocation import is_revoked, revoke_session
from .audit import audit_log_auth_event
from .users import validate_user_exists


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
        scopes_raw = user_data.get("scopes", [])
        is_admin = user_data.get("is_admin", False)
        
        # Нормализуем scopes в Set (для защиты от timing attacks и O(1) проверки)
        if isinstance(scopes_raw, list):
            scopes = set(scopes_raw)
        elif isinstance(scopes_raw, set):
            scopes = scopes_raw
        else:
            scopes = set()
        
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
                message=f"Error revoking all sessions for user {user_id}: {e}",
                module="api"
            )
        except Exception:
            pass
        return revoked_count
