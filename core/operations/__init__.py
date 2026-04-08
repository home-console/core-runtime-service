"""
Operations subsystem — first-class entity for all system-level actions.

Operation is immutable audit trail + execution context.
All critical actions MUST be executed through operations.

Поддерживает Capability Protocol v1:
- Remote provider health monitoring
- Retryable error handling
- Timeout enforcement
"""

from core.operations.component import OperationsComponent
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
from core.operations.worker_dependencies import WorkerDependencies
from core.operations.dedup_contract import (
    DEFAULT_DEDUP_TTL_SECONDS,
    DEDUP_STORAGE_NAMESPACE,
    OPERATION_READY_EVENT_TYPE,
    PROCESSED_EVENT_KEY_PREFIX,
    PROCESSED_OPERATION_KEY_PREFIX,
    storage_key_for_event,
    storage_key_for_operation,
)

# Re-export для обратной совместимости
__all__ = [
    # Models
    "Operation",
    "OperationStatus",
    "OperationInitiatorKind",
    "OperationError",
    "OperationInitiator",
    "TERMINAL_STATUSES",
    # Component
    "OperationsComponent",
    # Dependencies
    "WorkerDependencies",
    # Manager
    "OperationManager",
    # Internal components (для расширенного использования)
    "OperationHandlerRegistry",
    "OperationExecutor",
    "OperationStorage",
    # Dedup / at-least-once contract (G1)
    "DEFAULT_DEDUP_TTL_SECONDS",
    "DEDUP_STORAGE_NAMESPACE",
    "OPERATION_READY_EVENT_TYPE",
    "PROCESSED_EVENT_KEY_PREFIX",
    "PROCESSED_OPERATION_KEY_PREFIX",
    "storage_key_for_event",
    "storage_key_for_operation",
]
