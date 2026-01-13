"""
Utility functions — вспомогательные функции для auth.
"""

from typing import List, Set, Optional, Union
from .context import RequestContext


def validate_scopes(scopes: Union[List[str], Set[str]]) -> bool:
    """
    Валидирует формат scopes.
    
    Args:
        scopes: список scopes
    
    Returns:
        True если все scopes валидны, False если нет
    """
    # Поддерживаем как List, так и Set
    if not isinstance(scopes, (list, set)):
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


def check_service_scope(context: Optional[RequestContext], service_name: str) -> bool:
    """
    Проверяет, есть ли у контекста права на вызов сервиса.
    
    DEPRECATED: Используйте authz.check() вместо этого.
    
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
    parts = service_name.split(".", 1)
    if len(parts) < 2:
        return False
    
    namespace = parts[0]
    action = parts[1]
    
    # Проверяем scopes
    required_scope_exact = f"{namespace}.{action}"
    required_scope_wildcard = f"{namespace}.*"
    
    if "*" in context.scopes:
        return True
    
    if required_scope_exact in context.scopes:
        return True
    
    if required_scope_wildcard in context.scopes:
        return True
    
    return False
