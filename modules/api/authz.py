"""
Authorization Policy Layer — единая точка авторизационных проверок.

Цель: Единая точка, через которую система отвечает на вопрос:
"Разрешено ли выполнить действие?"

Архитектура:
- Использует RequestContext из auth.py
- Scope-based authorization (действие → scope)
- Resource-Based Authorization с ACL (ownership + shared_with)
- Self-service проверки для auth операций
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
    
    # OAuth Yandex
    "oauth_yandex.get_status": "oauth.read",
    "oauth_yandex.get_authorize_url": "oauth.read",
    "oauth_yandex.configure": "oauth.write",
    "oauth_yandex.exchange_code": "oauth.write",
    "oauth_yandex.validate": "oauth.read",
    "oauth_yandex.get_tokens": "oauth.read",
    "oauth_yandex.set_tokens": "oauth.write",
    
    # Auth management
    "admin.auth.create_api_key": "admin.*",
    "admin.auth.list_api_keys": "admin.*",
    "admin.auth.create_user": "admin.*",
    "admin.auth.list_users": "admin.*",
    "admin.auth.set_password": "admin.*",  # Self-service проверка через resource
    "admin.auth.change_password": "admin.*",  # Self-service проверка через resource
    "admin.auth.list_sessions": "admin.*",  # Self-service проверка через resource
    "admin.auth.revoke_session": "admin.*",
    "admin.auth.revoke_all_sessions": "admin.*",  # Self-service проверка через resource
    "admin.auth.revoke_api_key": "admin.*",
    "admin.auth.rotate_api_key": "admin.*",
    
    # Admin (wildcard - все admin.* действия требуют admin прав)
    # Проверяется отдельно через action.startswith("admin.")
}


def check(ctx: Optional[RequestContext], action: str, resource: Optional[Dict[str, Any]] = None) -> bool:
    """
    Проверяет, разрешено ли выполнить действие.
    
    Поддерживает Resource-Based Authorization с ACL (Ownership + Shared Resources).
    
    Args:
        ctx: RequestContext или None
        action: действие (например, "devices.get", "admin.v1.runtime")
        resource: ресурс с метаданными (owner_id, shared_with, user_id и т.д.)
    
    Returns:
        True если разрешено, False если запрещено
    
    Правила проверки действия:
    - Если ctx is None → False (кроме admin.auth.create_api_key при отсутствии ключей и oauth_yandex.*)
    - Если is_admin=True → True (полный доступ)
    - Если action начинается с "admin." → требуется "admin.*"
    - Иначе проверяем mapping: action → required scope
    
    Правила проверки ресурса (если resource предоставлен):
    - Ownership: если owner_id == ctx.user_id → разрешено
    - Shared access: если ctx.user_id в shared_with → разрешено
    - Self-service: для auth операций разрешено если target_user_id == ctx.user_id
    - Admin override: если ctx.is_admin → разрешено
    """
    # Специальный случай: создание первого API key разрешено без авторизации
    # Проверяем через resource, который передаётся из handler
    if action == "admin.auth.create_api_key" and resource and resource.get("allow_first_key"):
        return True
    
    # Специальный случай: OAuth эндпоинты публичные (не требуют авторизации)
    # Они используются для настройки OAuth до авторизации
    if action.startswith("oauth_yandex."):
        return True
    
    # Специальный случай: login публичный (не требует авторизации)
    if action == "admin.auth.login":
        return True
    
    # Нет контекста → нет доступа
    if ctx is None:
        return False
    
    # Администраторы имеют полный доступ (включая все ресурсы)
    if ctx.is_admin:
        return True
    
    # Полный wildcard даёт доступ ко всему (но проверяем ресурс отдельно)
    has_wildcard_scope = "*" in ctx.scopes
    
    # Проверяем права на действие (scope-based)
    action_allowed = False
    
    # Административные действия требуют admin прав
    if action.startswith("admin."):
        required_scope = "admin.*"
        action_allowed = required_scope in ctx.scopes or has_wildcard_scope
    else:
        # Ищем required scope в mapping
        required_scope = ACTION_SCOPE_MAP.get(action)
        
        # Если action не найден в mapping → доступ запрещён
        if required_scope is None:
            action_allowed = has_wildcard_scope
        else:
            # Проверяем scopes
            if required_scope in ctx.scopes:
                action_allowed = True
            elif "." in required_scope:
                namespace = required_scope.split(".")[0]
                namespace_wildcard = f"{namespace}.*"
                if namespace_wildcard in ctx.scopes:
                    action_allowed = True
            action_allowed = action_allowed or has_wildcard_scope
    
    # Если нет прав на действие → запрещаем
    if not action_allowed:
        return False
    
    # Проверяем права на ресурс (Resource-Based Authorization)
    if resource:
        # 1. Ownership проверка
        if "owner_id" in resource:
            owner_id = resource["owner_id"]
            if ctx.user_id == owner_id:
                return True  # Владелец имеет доступ
        
        # 2. Shared access (ACL)
        if "shared_with" in resource:
            shared_with = resource["shared_with"]
            if isinstance(shared_with, list) and ctx.user_id in shared_with:
                return True  # Пользователь в списке shared_with
        
        # 3. Self-service для auth операций
        if action in ["admin.auth.change_password", "admin.auth.set_password", 
                      "admin.auth.revoke_all_sessions", "admin.auth.list_sessions"]:
            target_user_id = resource.get("user_id")
            if target_user_id and ctx.user_id == target_user_id:
                return True  # Пользователь управляет своим аккаунтом
        
        # 4. Если ресурс указан, но нет совпадений → запрещаем
        # (кроме случаев, когда resource необязателен для действия)
        # Для некоторых действий resource может быть None (например, devices.list)
        # В этом случае проверяем только действие
        if "owner_id" in resource or "shared_with" in resource or "user_id" in resource:
            # Ресурс указан, но нет доступа → запрещаем
            return False
    
    # Если нет проверок ресурса или они пройдены → разрешаем
    return True


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
