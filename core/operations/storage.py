"""
OperationStorage - персистентность операций.

Отвечает за сохранение и загрузку операций из storage.
"""

import uuid
from typing import Optional, List, Any

from core.operations.models import Operation, OperationInitiator


class OperationStorage:
    """
    Хранилище операций.
    
    Отвечает за персистентность операций в storage.
    """
    
    def __init__(self, runtime: Any):
        """
        Инициализация хранилища.
        
        Args:
            runtime: экземпляр CoreRuntime
        """
        self.runtime = runtime
    
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
        operation_id = f"op-{uuid.uuid4().hex[:12]}"
        
        operation = Operation(
            operation_id=operation_id,
            op_type=op_type,
            params=params,
            initiator=initiator,
            parent_operation_id=parent_operation_id,
        )
        
        # Persist to storage
        await self.persist(operation)
        
        return operation
    
    async def get(self, operation_id: str) -> Optional[Operation]:
        """
        Retrieve operation from storage.
        
        Args:
            operation_id: Operation ID
            
        Returns:
            Operation or None if not found
        """
        data = await self.runtime.storage.get("operations", operation_id)
        if data is None:
            return None
        return Operation.from_dict(data)
    
    async def list(self, limit: int = 100, offset: int = 0) -> List[Operation]:
        """
        List operations (newest first).
        
        Args:
            limit: Maximum number of operations to return
            offset: Offset for pagination
            
        Returns:
            List of operations
        """
        try:
            keys = await self.runtime.storage.list_keys("operations")
        except Exception:
            return []
        
        # Fetch all and sort by created_at descending
        operations = []
        for key in keys:
            try:
                data = await self.runtime.storage.get("operations", key)
                if data:
                    operations.append(Operation.from_dict(data))
            except Exception:
                pass
        
        # Sort by created_at descending
        operations.sort(key=lambda op: op.created_at, reverse=True)
        
        # Apply pagination
        return operations[offset:offset + limit]
    
    async def persist(self, operation: Operation) -> None:
        """
        Persist operation state to storage.
        
        Args:
            operation: Operation to persist
        """
        await self.runtime.storage.set(
            "operations",
            operation.operation_id,
            operation.to_dict()
        )
