"""
OperationManager - Facade для управления операциями.

Координирует работу специализированных компонентов:
- OperationHandlerRegistry: регистрация обработчиков
- OperationExecutor: выполнение операций
- OperationStorage: персистентность операций
"""

from typing import Any, Optional, List

from core.operations.models import (
    Operation,
    Attempt,
    OperationInitiator,
    OperationStatus,
)
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
        self._registry = OperationHandlerRegistry()
        self._storage = OperationStorage(runtime)
        self._executor: IOperationExecutor = OperationExecutor(self._registry, runtime, self._storage)
    
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

    async def persist_operation(self, operation: Operation) -> None:
        """
        Persist operation state to storage.
        
        Public API for OperationWorker to persist operations without accessing _storage directly.

        Args:
            operation: Operation to persist
        """
        await self._storage.persist(operation)

    async def ensure_attempt_created(
        self,
        attempt_id: str,
        operation_id: str,
        attempt_index: int,
    ) -> None:
        """
        Ensure attempt record exists in storage.
        
        Public API for OperationWorker without accessing _storage directly.

        Args:
            attempt_id: Attempt ID
            operation_id: Operation ID
            attempt_index: Attempt index
        """
        await self._storage.ensure_attempt_created(attempt_id, operation_id, attempt_index)

    async def try_claim_attempt(
        self,
        attempt_id: str,
        worker_id: str,
        lease_ttl: int,
    ) -> tuple[bool, Optional[str]]:
        """
        Try to claim attempt for execution.
        
        Public API for OperationWorker without accessing _storage directly.

        Args:
            attempt_id: Attempt ID
            worker_id: Worker ID claiming the attempt
            lease_ttl: Lease TTL in seconds

        Returns:
            Tuple of (success, claim_token)
        """
        return await self._storage.try_claim_attempt(attempt_id, worker_id, lease_ttl)

    async def get_attempt(self, attempt_id: str) -> Optional[Attempt]:
        """
        Get attempt by ID.
        
        Public API for OperationWorker without accessing _storage directly.

        Args:
            attempt_id: Attempt ID

        Returns:
            Attempt or None
        """
        return await self._storage.get_attempt(attempt_id)

    async def persist_attempt(self, attempt: Attempt) -> None:
        """
        Persist attempt state.
        
        Public API for OperationWorker without accessing _storage directly.

        Args:
            attempt: Attempt to persist
        """
        await self._storage.persist_attempt(attempt)

    def get_executor(self) -> Any:
        """
        Get operation executor.
        
        Public API for OperationWorker without accessing _executor directly.

        Returns:
            Operation executor instance
        """
        return self._executor

    async def create(
        self,
        op_type: str,
        params: dict,
        initiator: OperationInitiator,
        parent_operation_id: Optional[str] = None,
        retry_count: int = 0,
        max_retries: int = 2,
        next_retry_at: Optional[float] = None,
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
        return await self._storage.create(
            op_type,
            params,
            initiator,
            parent_operation_id,
            retry_count,
            max_retries,
            next_retry_at,
        )
    
    async def get(self, operation_id: str) -> Optional[Operation]:
        """
        Retrieve operation from storage.
        
        Args:
            operation_id: Operation ID
            
        Returns:
            Operation or None if not found
        """
        return await self._storage.get(operation_id)
    
    async def list(
        self,
        limit: int = 100,
        offset: int = 0,
        status: Optional[str] = None,
    ) -> list[Operation]:
        """
        List operations (newest first).
        
        Args:
            limit: Maximum number of operations to return
            offset: Offset for pagination
            
        Returns:
            List of operations
        """
        operations = await self._storage.list(limit, offset)
        if status is None:
            return operations

        return [op for op in operations if op.status.value == str(status)]

    # ========== ATTEMPT HISTORY ==========

    async def get_attempts(self, operation_id: str) -> Optional[List[Attempt]]:
        """
        Read API: return ordered attempt history for an operation.
        """
        return await self._storage.get_attempts(operation_id)
    
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
        # Worker is the execution owner; OperationManager delegates.
        worker = getattr(self.runtime, "worker", None)
        if worker is None or not hasattr(worker, "execute_operation_now"):
            raise RuntimeError("OperationWorker not available for execution")
        return await worker.execute_operation_now(operation)
    
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

        operation.cancel_requested = True
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

        new_op = await self.create(
            op_type=original.type,
            params=original.params,
            initiator=original.initiator,
            parent_operation_id=operation_id,
            retry_count=original.retry_count,
            max_retries=original.max_retries,
        )

        return new_op
    
    # ========== INTERNAL METHODS (для обратной совместимости) ==========
    
    def _find_handler(self, operation_type: str):
        """Internal method для обратной совместимости."""
        return self._registry.find_handler(operation_type)
    
    async def _persist(self, operation: Operation) -> None:
        """Internal method для обратной совместимости."""
        await self._storage.persist(operation)
