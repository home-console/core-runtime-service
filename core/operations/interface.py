"""
Operation Executor Interface - контракт для исполнителя операций.

Определяет минимальный интерфейс для компонентов, исполняющих операции,
позволяя инвертировать зависимости и улучшить тестируемость.
"""

from typing import Protocol, runtime_checkable
from core.operations.models import Operation


@runtime_checkable
class IOperationExecutor(Protocol):
    """
    Interface for operation execution.
    
    Defines contract for any component that executes operations,
    enabling dependency inversion and decoupling from concrete implementations.
    """
    
    async def execute(self, operation: Operation) -> Operation:
        """
        Execute an operation and return its result.
        
        Args:
            operation: Operation to execute with type, params, etc.
            
        Returns:
            Operation with updated status, result, or error.
            
        Raises:
            No exceptions should be raised; all failures should be reflected
            in operation.status and operation.error.
        """
        ...
