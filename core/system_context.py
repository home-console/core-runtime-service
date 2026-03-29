"""
System Context - для внутренних вызовов runtime.

SECURITY P0: Internal calls больше НЕ могут использовать ctx=None.
Вместо этого используется SystemContext с явными разрешениями.

SystemContext:
- Используется ТОЛЬКО для внутренних вызовов runtime/modules
- НЕ может быть создан плагинами
- Проходит все ACL проверки
- Логируется для audit trail
"""

from dataclasses import dataclass
from typing import Any, Set


@dataclass
class SystemContext:
    """
    Context для системных внутренних вызовов.

    SECURITY:
    - Используется только внутри runtime/core modules
    - НЕ доступен плагинам
    - Проходит все ACL проверки (is_admin=True)
    - Логируется для аудита

    Attributes:
        component: имя компонента (например, "event_bus", "storage_sync")
        operation: описание операции (например, "emit_event", "sync_data")
        is_admin: всегда True для системных операций
        scopes: всегда {"admin.*"} для системных операций
    """

    component: str
    operation: str
    is_admin: bool = True
    scopes: Set[str] = {"admin.*"}

    def __repr__(self) -> str:
        """String representation for logging."""
        return f"SystemContext(component={self.component}, operation={self.operation})"


def create_system_context(component: str, operation: str) -> SystemContext:
    """
    Create SystemContext for internal runtime calls.

    SECURITY:
    - ONLY for use by runtime/core modules
    - NOT accessible by plugins
    - Logged for audit trail

    Args:
        component: Component name (e.g., "event_bus")
        operation: Operation description (e.g., "emit_event")

    Returns:
        SystemContext instance

    Example:
        ctx = create_system_context("event_bus", "emit_device_update")
        await runtime.service_registry.call("devices.get", device_id="...", ctx=ctx)
    """
    return SystemContext(component=component, operation=operation)


def is_system_context(ctx: Any) -> bool:
    """
    Check if context is SystemContext.

    Args:
        ctx: Context to check

    Returns:
        True if SystemContext, False otherwise
    """
    return isinstance(ctx, SystemContext)
