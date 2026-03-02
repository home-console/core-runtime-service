"""
Централизованный ACL helper (фасад над PolicyEngine).

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
from core.policy_engine import get_policy_engine


def is_privileged(ctx: Any) -> bool:
    """
    Публичный helper для проверки привилегий (admin.* / is_admin / *).
    
    Делегирует в PolicyEngine.
    """
    policy_engine = get_policy_engine()
    return policy_engine.is_privileged(ctx)


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
    policy_engine = get_policy_engine()
    policy_engine.enforce_admin(ctx)


def enforce_policy(ctx: Any, resource: str, obj: Any) -> None:
    """
    Применяет политику к ресурсу.
    - Если ctx None — считается trusted internal.
    - Если политика не найдена — no-op (fail-open для обратной совместимости, можно ужесточить).
    
    Делегирует в PolicyEngine.
    """
    policy_engine = get_policy_engine()
    policy_engine.enforce_policy(ctx, resource, obj)


def filter_with_policy(ctx: Any, resource: str, items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Фильтрует список объектов по политике. Если ctx None — возвращает как есть.
    
    Делегирует в PolicyEngine.
    """
    policy_engine = get_policy_engine()
    return policy_engine.filter_with_policy(ctx, resource, items)


def current_context() -> Any:
    """
    Утилита для явного доступа к текущему RequestContext (может быть None).
    
    Делегирует в PolicyEngine.
    """
    policy_engine = get_policy_engine()
    return policy_engine.current_context()

