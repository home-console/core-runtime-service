"""
Core contexts package - unified context types for Runtime, Operations, and System.

Provides:
- RuntimeContext: ограниченный контекст для модулей/плагинов
- OperationContext: для трассировки операций через observability
- SystemContext: для системных внутренних вызовов
"""

from core.runtime_context import RuntimeContext
from core.operation_context import (
    OperationContextProvider,
    set_operation_context_provider,
    get_operation_context_provider,
    get_operation_id,
    set_operation_id,
)
from core.system_context import (
    SystemContext,
    create_system_context,
    is_system_context,
)

__all__ = [
    "RuntimeContext",
    "OperationContextProvider",
    "set_operation_context_provider",
    "get_operation_context_provider",
    "get_operation_id",
    "set_operation_id",
    "SystemContext",
    "create_system_context",
    "is_system_context",
]
