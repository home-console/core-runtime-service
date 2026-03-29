"""
Operations subsystem — first-class entity for all system-level actions.

Operation is immutable audit trail + execution context.
All critical actions MUST be executed through operations.

Поддерживает Capability Protocol v1:
- Remote provider health monitoring
- Retryable error handling
- Timeout enforcement
"""

from core.operations.executor import OperationExecutor
from core.operations.manager import OperationManager
from core.operations.models import (
    TERMINAL_STATUSES,
    Operation,
    OperationError,
    OperationInitiator,
    OperationInitiatorKind,
    OperationStatus,
)
from core.operations.registry import OperationHandlerRegistry
from core.operations.storage import OperationStorage

# Re-export для обратной совместимости
__all__ = [
    # Models
    "Operation",
    "OperationStatus",
    "OperationInitiatorKind",
    "OperationError",
    "OperationInitiator",
    "TERMINAL_STATUSES",
    # Manager
    "OperationManager",
    # Internal components (для расширенного использования)
    "OperationHandlerRegistry",
    "OperationExecutor",
    "OperationStorage",
]
