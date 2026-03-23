"""
Operations subsystem — first-class entity for all system-level actions.

Operation is immutable audit trail + execution context.
All critical actions MUST be executed through operations.

Поддерживает Capability Protocol v1:
- Remote provider health monitoring
- Retryable error handling
- Timeout enforcement
"""

from core.operations.models import (
    Operation,
    OperationStatus,
    OperationInitiatorKind,
    OperationError,
    OperationInitiator,
    TERMINAL_STATUSES,
)
from core.operations.registry import OperationHandlerRegistry
from core.operations.executor import OperationExecutor
from core.operations.storage import OperationStorage
from core.operations.manager import OperationManager

# Re-export для обратной совместимости
__all__ = [
    # Models
    'Operation',
    'OperationStatus',
    'OperationInitiatorKind',
    'OperationError',
    'OperationInitiator',
    'TERMINAL_STATUSES',
    # Manager
    'OperationManager',
    # Internal components (для расширенного использования)
    'OperationHandlerRegistry',
    'OperationExecutor',
    'OperationStorage',
]
