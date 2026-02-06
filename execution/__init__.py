"""
Execution Layer (D3)

Execution — подключаемая подсистема (policy + backend), которая исполняет operations
в разных режимах (in-process / process / container) без знания доменов, UI, SDK, automation.
"""

from .controller import ExecutionControllerImpl
from .policy import ExecutionPolicy, StateExecutionPolicy
from .backend import (
    BackendId,
    ExecutionBackend,
    InProcessBackend,
    ProcessBackend,
    ContainerBackend,
    OperationResult,
)
from .trace import ExecutionTrace

__all__ = [
    "ExecutionControllerImpl",
    "ExecutionPolicy",
    "StateExecutionPolicy",
    "BackendId",
    "ExecutionBackend",
    "InProcessBackend",
    "ProcessBackend",
    "ContainerBackend",
    "OperationResult",
    "ExecutionTrace",
]

