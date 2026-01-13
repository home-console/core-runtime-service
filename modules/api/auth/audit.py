"""
Audit logging — логирование всех auth событий для аудита.
"""

from typing import Any, Optional, Dict
import time
import hashlib

from .constants import AUTH_AUDIT_LOG_NAMESPACE


async def audit_log_auth_event(
    runtime: Any,
    event_type: str,
    subject: str,
    details: Optional[Dict[str, Any]] = None,
    success: bool = False
) -> None:
    """
    Логирует auth событие для аудита.
    
    Args:
        runtime: экземпляр CoreRuntime
        event_type: тип события ("auth_success", "auth_failure", "key_revoked", etc.)
        subject: идентификатор субъекта (API key, session_id, user_id)
        details: дополнительные детали (IP, path, user_agent, etc.)
        success: успешность операции
    """
    try:
        audit_entry = {
            "timestamp": time.time(),
            "event_type": event_type,
            "subject": subject[:64] if subject else "unknown",
            "success": success,
            "details": details or {}
        }
        
        # Сохраняем в audit log
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
