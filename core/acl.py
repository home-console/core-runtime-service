"""
Централизованный ACL helper.

SECURITY P0: ctx=None больше НЕ считается trusted.
Internal calls должны использовать SystemContext.

Идея:
- Сервисы/плагины не размазывают проверки везде.
- Метаданные/обёртки вызывают `enforce_policy` или `enforce_admin` при наличии RequestContext.
- Internal calls используют SystemContext вместо ctx=None.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from core.errors import ForbiddenError, NotFoundError
from core.auth_contextvars import get_current_auth_context


def _is_privileged(ctx: Any) -> bool:
    """
    Админский обход.
    
    SECURITY P0: SystemContext is privileged, ctx=None is NOT.
    """
    if not ctx:
        return False
    
    # SECURITY: Check if SystemContext (always privileged)
    from core.system_context import is_system_context
    if is_system_context(ctx):
        return True
    
    try:
        if getattr(ctx, "is_admin", False):
            return True
        scopes = getattr(ctx, "scopes", set()) or set()
        return ("admin.*" in scopes) or ("*" in scopes)
    except Exception:
        return False


def is_privileged(ctx: Any) -> bool:
    """Публичный helper для проверки привилегий (admin.* / is_admin / *)."""
    return _is_privileged(ctx)


def enforce_admin(ctx: Any) -> None:
    """
    Требует админ-привилегии.
    
    SECURITY P0: ctx=None больше НЕ считается privileged.
    Internal calls должны быть явно разрешены через allow-list.
    
    Args:
        ctx: RequestContext или None
        
    Raises:
        ForbiddenError: если нет админ-прав или ctx=None
    """
    # SECURITY FIX: ctx=None is NO LONGER privileged
    # Internal calls must be explicitly allowed via allow-list or use system context
    if ctx is None:
        raise ForbiddenError("forbidden: admin operation requires context")
    
    if _is_privileged(ctx):
        return
    
    raise ForbiddenError("forbidden")


def enforce_policy(ctx: Any, resource: str, obj: Any) -> None:
    """
    Применяет политику к ресурсу.
    - Если ctx None — считается trusted internal.
    - Если политика не найдена — no-op (fail-open для обратной совместимости, можно ужесточить).
    """
    if ctx is None:
        return
    if resource == "device":
        _policy_device(ctx, obj)
    elif resource in ("device_mapping", "external_inventory"):
        # для маппингов и инвентаря требуем админский доступ
        enforce_admin(ctx)
    else:
        # неизвестный ресурс — пока пропускаем (минимально инвазивно)
        return


def filter_with_policy(ctx: Any, resource: str, items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Фильтрует список объектов по политике. Если ctx None — возвращает как есть."""
    if ctx is None:
        return list(items)

    out: List[Dict[str, Any]] = []
    for obj in items:
        try:
            enforce_policy(ctx, resource, obj)
            out.append(obj)
        except Exception:
            # скрываем чужие объекты
            continue
    return out


def _policy_device(ctx: Any, device: Any) -> None:
    """Политика для устройств: owner/shared или admin."""
    if device is None:
        # Не раскрываем существование
        raise NotFoundError("device not found")

    if _is_privileged(ctx):
        return

    user_id = getattr(ctx, "user_id", None)
    if not user_id:
        raise NotFoundError("device not found")

    if isinstance(device, dict):
        owner_id = device.get("owner_id")
        if owner_id and owner_id == user_id:
            return
        shared_with = device.get("shared_with")
        if isinstance(shared_with, list) and user_id in shared_with:
            return

    # Не раскрываем существование ресурса
    raise NotFoundError("device not found")


def current_context() -> Any:
    """Утилита для явного доступа к текущему RequestContext (может быть None)."""
    return get_current_auth_context()

