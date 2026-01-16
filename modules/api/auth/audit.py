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
        # Проверяем и нормализуем subject
        safe_subject = "unknown"
        if subject:
            if isinstance(subject, str):
                safe_subject = subject[:64]
            else:
                safe_subject = str(subject)[:64]
        
        # Нормализуем details - должен быть dict
        safe_details = {}
        if details:
            if isinstance(details, dict):
                safe_details = details
            else:
                safe_details = {"raw_details": str(details)[:500]}
        
        audit_entry = {
            "timestamp": time.time(),
            "event_type": event_type,
            "subject": safe_subject,
            "success": success,
            "details": safe_details
        }
        
        # Сохраняем в audit log
        subject_bytes = safe_subject.encode() if isinstance(safe_subject, str) else str(safe_subject).encode()
        audit_key = f"{int(time.time() * 1000)}_{hashlib.sha256(subject_bytes).hexdigest()[:16]}"
        await runtime.storage.set(AUTH_AUDIT_LOG_NAMESPACE, audit_key, audit_entry)
    
    except Exception as e:
        # Не падаем при ошибке audit logging
        try:
            await runtime.service_registry.call(
                "logger.log",
                level="error",
                message=f"Audit logging error: {e}",
                module="api",
                context={
                    "event_type": event_type,
                    "subject_type": type(subject).__name__ if subject else "None",
                    "subject_value": str(subject)[:100] if subject else "None",
                    "error_type": type(e).__name__,
                    "error_message": str(e)
                }
            )
        except Exception:
            pass
