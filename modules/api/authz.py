"""
Authorization Policy Layer — единая точка авторизационных проверок.

Цель: Единая точка, через которую система отвечает на вопрос:
"Разрешено ли выполнить действие?"

Архитектура:
- Использует RequestContext из auth.py
- Простая логика на основе scopes
- Action → scope mapping
- НЕ добавляет роли, ownership, ACL
- НЕ логирует
- НЕ мутирует состояние
"""

from typing import Optional, Dict, Any
from modules.api.auth import RequestContext


class AuthorizationError(Exception):
    """Исключение при отказе в авторизации."""
    pass


# Mapping: action → required scope
# Формат scope: "namespace.action" (совместимо с существующим форматом scopes)
# Action соответствует service_name из ServiceRegistry
# Для read операций используется "namespace.read", для write - "namespace.write"
ACTION_SCOPE_MAP: Dict[str, str] = {
    # Devices
    "devices.list": "devices.read",
    "devices.get": "devices.read",
    "devices.set_state": "devices.write",
    "devices.list_external": "devices.read",
    "devices.list_mappings": "devices.read",
    "devices.create_mapping": "devices.write",
    "devices.delete_mapping": "devices.write",
    "devices.auto_map_external": "devices.write",
    
    # Automation
    "automation.trigger": "automation.write",
    "automation.list": "automation.read",
    "automation.get": "automation.read",
    "automation.create": "automation.write",
    "automation.update": "automation.write",
    "automation.delete": "automation.write",
    
    # Presence
    "presence.set": "presence.write",
    "presence.get": "presence.read",
    
    # Admin (wildcard - все admin.* действия требуют admin прав)
    # Проверяется отдельно через action.startswith("admin.")
}


def check(ctx: Optional[RequestContext], action: str, resource: Optional[Dict[str, Any]] = None) -> bool:
    """
    Проверяет, разрешено ли выполнить действие.
    
    Args:
        ctx: RequestContext или None
        action: действие (например, "devices.get", "admin.v1.runtime")
        resource: ресурс (принимается, но не используется - для будущих стадий)
    
    Returns:
        True если разрешено, False если запрещено
    
    Правила:
    - Если ctx is None → False
    - Если is_admin=True → True (полный доступ)
    - Если action начинается с "admin." → требуется "admin.*"
    - Иначе проверяем mapping: action → required scope
    - Если action не найден в mapping → False
    """
    # Нет контекста → нет доступа
    if ctx is None:
        return False
    
    # Администраторы имеют полный доступ
    if ctx.is_admin:
        return True
    
    # Полный wildcard даёт доступ ко всему
    if "*" in ctx.scopes:
        return True
    
    # Административные действия требуют admin прав
    if action.startswith("admin."):
        required_scope = "admin.*"
        return required_scope in ctx.scopes
    
    # Ищем required scope в mapping
    required_scope = ACTION_SCOPE_MAP.get(action)
    
    # Если action не найден в mapping → доступ запрещён
    if required_scope is None:
        return False
    
    # Проверяем scopes
    # Поддерживаем:
    # - Точное совпадение (например, "devices.read")
    # - Wildcard для namespace (например, "devices.*")
    
    if required_scope in ctx.scopes:
        return True
    
    # Проверяем wildcard для namespace
    # Например, required_scope="devices.read" → проверяем "devices.*"
    if "." in required_scope:
        namespace = required_scope.split(".")[0]
        namespace_wildcard = f"{namespace}.*"
        if namespace_wildcard in ctx.scopes:
            return True
    
    return False


def require(ctx: Optional[RequestContext], action: str, resource: Optional[Dict[str, Any]] = None) -> None:
    """
    Требует разрешения на выполнение действия.
    
    Вызывает check() и бросает AuthorizationError если доступ запрещён.
    
    Args:
        ctx: RequestContext или None
        action: действие
        resource: ресурс (принимается, но не используется)
    
    Raises:
        AuthorizationError: если доступ запрещён
    """
    if not check(ctx, action, resource):
        raise AuthorizationError(f"Authorization failed for action: {action}")


def get_required_scope(action: str) -> Optional[str]:
    """
    Возвращает required scope для действия.
    
    Используется для документирования и отладки.
    
    Args:
        action: действие
    
    Returns:
        Required scope или None если не найден
    """
    if action.startswith("admin."):
        return "admin.*"
    return ACTION_SCOPE_MAP.get(action)
