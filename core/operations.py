"""
Operations subsystem — first-class entity for all system-level actions.

Operation is immutable audit trail + execution context.
All critical actions MUST be executed through operations.
"""

import uuid
import time
from typing import Any, Dict, Optional, List, Callable, Awaitable
from enum import Enum
from dataclasses import dataclass, asdict


class OperationStatus(Enum):
    """Operation lifecycle statuses."""
    PENDING = "pending"      # Created, not yet started
    RUNNING = "running"      # Currently executing
    SUCCESS = "success"      # Completed successfully
    FAILED = "failed"        # Execution failed
    CANCELLED = "cancelled"  # User cancelled


class OperationInitiatorKind(Enum):
    """Who initiated the operation."""
    ADMIN = "admin"      # Explicit admin action
    SYSTEM = "system"    # Background/automatic action


@dataclass
class OperationError:
    """Error details for failed operation."""
    code: str                    # Retryable? Transient? UserError?
    message: str
    details: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            **({"details": self.details} if self.details else {})
        }


@dataclass
class OperationInitiator:
    """Who initiated this operation."""
    kind: OperationInitiatorKind
    user_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind.value,
            **({"user_id": self.user_id} if self.user_id else {})
        }


class Operation:
    """
    First-class operation entity.
    
    Immutable once created, status transitions are the only mutations.
    Every critical action is tracked as operation.
    """
    
    def __init__(
        self,
        operation_id: str,
        op_type: str,
        params: Dict[str, Any],
        initiator: OperationInitiator,
        parent_operation_id: Optional[str] = None,
    ):
        # Immutable fields
        self.operation_id = operation_id
        self.type = op_type
        self.params = params
        self.initiator = initiator
        self.parent_operation_id = parent_operation_id  # For retries
        
        # Timestamps
        self.created_at = time.time()
        self.started_at: Optional[float] = None
        self.finished_at: Optional[float] = None
        
        # Status + Result
        self.status = OperationStatus.PENDING
        self.error: Optional[OperationError] = None
        self.result: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize operation to dict."""
        data = {
            "operation_id": self.operation_id,
            "type": self.type,
            "params": self.params,
            "initiator": self.initiator.to_dict(),
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }
        
        if self.error:
            data["error"] = self.error.to_dict()
        
        if self.result:
            data["result"] = self.result
        
        if self.parent_operation_id:
            data["parent_operation_id"] = self.parent_operation_id
        
        return data
    
    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Operation":
        """Deserialize operation from dict."""
        initiator_data = data.get("initiator", {})
        initiator = OperationInitiator(
            kind=OperationInitiatorKind(initiator_data.get("kind", "system")),
            user_id=initiator_data.get("user_id")
        )
        
        op = Operation(
            operation_id=data["operation_id"],
            op_type=data["type"],
            params=data.get("params", {}),
            initiator=initiator,
            parent_operation_id=data.get("parent_operation_id")
        )
        
        op.status = OperationStatus(data.get("status", "pending"))
        op.created_at = data.get("created_at", time.time())
        op.started_at = data.get("started_at")
        op.finished_at = data.get("finished_at")
        op.result = data.get("result")
        
        if "error" in data and data["error"]:
            error_data = data["error"]
            op.error = OperationError(
                code=error_data.get("code"),
                message=error_data.get("message"),
                details=error_data.get("details")
            )
        
        return op


class OperationManager:
    """
    Manages operation lifecycle: create, execute, store, query.
    
    Coordinates:
    - Operation registry (types)
    - Storage persistence
    - Execution pipeline
    - Audit trail
    """
    
    def __init__(self, runtime: Any):
        self.runtime = runtime
        # Type name -> handler (async callable)
        self._handlers: Dict[str, Callable[[Any, Operation], Awaitable[Dict[str, Any]]]] = {}
        # Error codes that allow retry
        self._retryable_errors = {
            "timeout", "transient", "network", "device_offline", "integration_unavailable"
        }
    
    def register_handler(
        self,
        op_type: str,
        handler: Callable[[Any, Operation], Awaitable[Dict[str, Any]]]
    ) -> None:
        """
        Register handler for operation type.
        
        Handler signature: async def handler(runtime, operation) -> Dict[str, Any]
        """
        self._handlers[op_type] = handler

    def list_handler_types(self) -> List[str]:
        """Return list of registered operation type names (read-only, for Inspector)."""
        return list(self._handlers.keys())

    async def create(
        self,
        op_type: str,
        params: Dict[str, Any],
        initiator: OperationInitiator,
        parent_operation_id: Optional[str] = None,
    ) -> Operation:
        """Create and persist new operation."""
        operation_id = f"op-{uuid.uuid4().hex[:12]}"
        
        operation = Operation(
            operation_id=operation_id,
            op_type=op_type,
            params=params,
            initiator=initiator,
            parent_operation_id=parent_operation_id,
        )
        
        # Persist to storage
        await self.runtime.storage.set(
            "operations",
            operation_id,
            operation.to_dict()
        )
        
        return operation
    
    async def get(self, operation_id: str) -> Optional[Operation]:
        """Retrieve operation from storage."""
        data = await self.runtime.storage.get("operations", operation_id)
        if data is None:
            return None
        return Operation.from_dict(data)
    
    async def list(self, limit: int = 100, offset: int = 0) -> List[Operation]:
        """List operations (newest first)."""
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
    
    async def execute(self, operation: Operation) -> Operation:
        """
        Execute operation following pipeline:
        validate → authorize → run → persist.
        
        Operation status is updated in-place, result persisted.
        """
        try:
            # 1. Validate
            if operation.type not in self._handlers:
                operation.status = OperationStatus.FAILED
                operation.error = OperationError(
                    code="unknown_operation_type",
                    message=f"No handler for operation type: {operation.type}"
                )
                await self._persist(operation)
                return operation
            
            # 2. Mark as running
            operation.status = OperationStatus.RUNNING
            operation.started_at = time.time()
            await self._persist(operation)
            
            # 3. Execute handler with context
            handler = self._handlers[operation.type]
            context = {"runtime": self.runtime, "operation_id": operation.operation_id}
            result = await handler(operation.params, context)
            
            # 4. Mark success
            operation.status = OperationStatus.SUCCESS
            operation.result = result
            operation.finished_at = time.time()
            
        except Exception as e:
            # Any exception → failed operation
            operation.status = OperationStatus.FAILED
            operation.error = OperationError(
                code="execution_error",
                message=str(e)
            )
            operation.finished_at = time.time()
        
        # Persist final state
        await self._persist(operation)
        return operation
    
    async def cancel(self, operation_id: str) -> Optional[Operation]:
        """Cancel operation if possible (only PENDING or RUNNING)."""
        operation = await self.get(operation_id)
        if not operation:
            return None
        
        if operation.status not in (OperationStatus.PENDING, OperationStatus.RUNNING):
            return operation  # Already terminal
        
        operation.status = OperationStatus.CANCELLED
        operation.finished_at = time.time()
        await self._persist(operation)
        
        return operation
    
    async def retry(self, operation_id: str) -> Optional[Operation]:
        """
        Create new operation as retry of failed operation.
        
        Original operation's error must be retryable.
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
    
    async def _persist(self, operation: Operation) -> None:
        """Persist operation state to storage."""
        await self.runtime.storage.set(
            "operations",
            operation.operation_id,
            operation.to_dict()
        )


# Marker for retryable error codes
RETRYABLE_ERRORS = {
    "timeout", "transient", "network", "device_offline", 
    "integration_unavailable", "rate_limited"
}

# Marker for terminal status
TERMINAL_STATUSES = {OperationStatus.SUCCESS, OperationStatus.FAILED, OperationStatus.CANCELLED}
