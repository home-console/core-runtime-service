"""
Operation models - данные операций.

Содержит модели данных для операций: Operation, OperationStatus, OperationError, OperationInitiator.
"""

import time
from typing import Any, Dict, Optional
from enum import Enum
from dataclasses import dataclass


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


# Marker for retryable error codes
RETRYABLE_ERRORS = {
    "timeout", "transient", "network", "device_offline", 
    "integration_unavailable", "rate_limited"
}

# Marker for terminal status
TERMINAL_STATUSES = {OperationStatus.SUCCESS, OperationStatus.FAILED, OperationStatus.CANCELLED}
