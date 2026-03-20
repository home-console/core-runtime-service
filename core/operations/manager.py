"""
OperationManager - Facade для управления операциями.

Координирует работу специализированных компонентов:
- OperationHandlerRegistry: регистрация обработчиков
- OperationExecutor: выполнение операций
- OperationStorage: персистентность операций
"""

from typing import Any, Optional

from core.operations.models import Operation, OperationInitiator, OperationStatus
from core.operations.registry import OperationHandlerRegistry
from core.operations.interface import IOperationExecutor
from core.operations.executor import OperationExecutor
from core.operations.storage import OperationStorage


class OperationManager:
    """
    Manages operation lifecycle: create, execute, store, query.
    
    Поддерживает Capability Protocol v1:
    - Health monitoring for remote providers
    - Retryable error handling
    - Timeout enforcement from manifest
    
    Coordinates:
    - Operation registry (types)
    - Storage persistence
    - Execution pipeline
    - Audit trail
    """
    
    def __init__(self, runtime: Any):
        """
        Инициализация OperationManager.
        
        Args:
            runtime: экземпляр CoreRuntime
        """
        self.runtime = runtime
        
        # ExecutionController используется через runtime
        # Создаём компоненты
        self._registry = OperationHandlerRegistry(execution_router=None)
        self._storage = OperationStorage(runtime)
        self._executor: IOperationExecutor = OperationExecutor(self._registry, runtime, self._storage)
        
        # Error codes that allow retry
        self._retryable_errors = {
            "timeout", "transient", "network", "device_offline", "integration_unavailable"
        }
    
    # ========== HANDLER REGISTRATION ==========
    
    def register_handler(
        self,
        op_type: str,
        handler: Any
    ) -> None:
        """
        Register handler for operation type.
        
        Handler signature: async def handler(runtime, operation) -> Dict[str, Any]
        
        Args:
            op_type: Operation type name
            handler: Async handler function
        """
        self._registry.register(op_type, handler)
    
    def unregister_handler(self, op_type: str) -> None:
        """
        Unregister handler for operation type.
        
        Args:
            op_type: Operation type to unregister
        """
        self._registry.unregister(op_type)
    
    def list_handler_types(self) -> list[str]:
        """
        Return list of registered operation type names (read-only, for Inspector).
        
        Returns:
            List of operation type names
        """
        return self._registry.list_types()
    
    # ========== STORAGE OPERATIONS ==========
    
    async def create(
        self,
        op_type: str,
        params: dict,
        initiator: OperationInitiator,
        parent_operation_id: Optional[str] = None,
    ) -> Operation:
        """
        Create and persist new operation.
        
        Args:
            op_type: Operation type
            params: Operation parameters
            initiator: Operation initiator
            parent_operation_id: Optional parent operation ID for retries
            
        Returns:
            Created operation
        """
        return await self._storage.create(op_type, params, initiator, parent_operation_id)
    
    async def get(self, operation_id: str) -> Optional[Operation]:
        """
        Retrieve operation from storage.
        
        Args:
            operation_id: Operation ID
            
        Returns:
            Operation or None if not found
        """
        return await self._storage.get(operation_id)
    
    async def list(self, limit: int = 100, offset: int = 0) -> list[Operation]:
        """
        List operations (newest first).
        
        Args:
            limit: Maximum number of operations to return
            offset: Offset for pagination
            
        Returns:
            List of operations
        """
        return await self._storage.list(limit, offset)
    
    # ========== EXECUTION ==========
    
    async def execute(self, operation: Operation) -> Operation:
        """
        Execute operation following pipeline:
        validate → authorize → run → persist.
        
        Operation status is updated in-place, result persisted.
        
        Supports execution modes:
        1. in_process: direct handler call
        2. process: subprocess execution
        3. container: docker/podman execution
        4. remote: HTTP execution
        
        Args:
            operation: Operation to execute
            
        Returns:
            Operation with updated status and result
        """
        return await self._executor.execute(operation)
    
    async def cancel(self, operation_id: str) -> Optional[Operation]:
        """
        Cancel operation if possible (only PENDING or RUNNING).
        
        Args:
            operation_id: Operation ID to cancel
            
        Returns:
            Cancelled operation or None if not found
        """
        operation = await self.get(operation_id)
        if not operation:
            return None
        
        if operation.status not in (OperationStatus.PENDING, OperationStatus.RUNNING):
            return operation  # Already terminal
        
        operation.status = OperationStatus.CANCELLED
        import time
        operation.finished_at = time.time()
        await self._storage.persist(operation)
        
        return operation
    
    async def retry(self, operation_id: str) -> Optional[Operation]:
        """
        Create new operation as retry of failed operation.
        
        Original operation's error must be retryable.
        
        Args:
            operation_id: Operation ID to retry
            
        Returns:
            New operation for retry or None if retry not possible
        """
        original = await self.get(operation_id)
        if not original:
            return None
        
        # Only allow retry for failed operations
        if original.status != OperationStatus.FAILED:
            return None
        
        # Only if error code is retryable
        if original.error and original.error.code not in self._retryable_errors:
            return None
        
        # Create new operation as retry
        new_op = await self.create(
            op_type=original.type,
            params=original.params,
            initiator=original.initiator,
            parent_operation_id=operation_id,
        )
        
        return new_op
    
    # ========== INTERNAL METHODS (для обратной совместимости) ==========
    
    def _find_handler(self, operation_type: str):
        """Internal method для обратной совместимости."""
        return self._registry.find_handler(operation_type, self.runtime)
    
    async def _persist(self, operation: Operation) -> None:
        """Internal method для обратной совместимости."""
        await self._storage.persist(operation)
