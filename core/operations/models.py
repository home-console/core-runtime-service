"""
Operation models - данные операций.

Содержит модели данных для операций: Operation, OperationStatus, OperationError, OperationInitiator.
"""

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional


class OperationStatus(str, Enum):
    """Operation lifecycle statuses."""

    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    # Compatibility aliases (data-only aliases; no behavior).
    PENDING = CREATED
    SUCCESS = COMPLETED


class OperationInitiatorKind(Enum):
    """Who initiated the operation."""

    ADMIN = "admin"  # Explicit admin action
    SYSTEM = "system"  # Background/automatic action


class OperationError(str):
    """Error details for failed operation."""

    code: str
    message: str
    details: Optional[Dict[str, Any]]
    __slots__ = ("code", "message", "details")

    def __new__(cls, code: str, message: str, details: Optional[Dict[str, Any]] = None):
        obj = str.__new__(cls, message)
        obj.code = code
        obj.message = message
        obj.details = details
        return obj

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            **({"details": self.details} if self.details else {}),
        }


@dataclass
class OperationInitiator:
    """Who initiated this operation."""

    kind: OperationInitiatorKind
    user_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind.value,
            **({"user_id": self.user_id} if self.user_id else {}),
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
        retry_count: int = 0,
        max_retries: int = 2,
        next_retry_at: Optional[float] = None,
        idempotency_key: Optional[str] = None,
        cancel_requested: bool = False,
        timeout_seconds: Optional[int] = None,
        correlation_id: Optional[str] = None,
        causation_id: Optional[str] = None,
        source_event: Optional[str] = None,
        triggered_by: str = "manual",
    ):
        # Immutable fields
        self.operation_id = operation_id
        self.type = op_type
        self.params = params
        self.initiator = initiator
        self.parent_operation_id = parent_operation_id  # For retries
        self.retry_count = retry_count
        self.max_retries = max_retries
        self.next_retry_at = next_retry_at
        self.idempotency_key = idempotency_key
        self.cancel_requested = bool(cancel_requested)
        self.timeout_seconds = timeout_seconds
        # Causality/observability metadata (purely metadata; execution flow must not depend on it).
        self.correlation_id = correlation_id
        self.causation_id = causation_id
        self.source_event = source_event
        self.triggered_by = triggered_by

        # Timestamps
        self.created_at = time.time()
        self.started_at: Optional[float] = None
        self.finished_at: Optional[float] = None

        # Status + Result
        self.status = OperationStatus.CREATED
        self.error: Optional[OperationError] = None
        self.result: Optional[Dict[str, Any]] = None

    @property
    def id(self) -> str:
        return self.operation_id

    def to_dict(self) -> Dict[str, Any]:
        """Serialize operation to dict."""
        data = {
            "operation_id": self.operation_id,
            "type": self.type,
            "params": self.params,
            "initiator": self.initiator.to_dict(),
            "idempotency_key": self.idempotency_key,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "source_event": self.source_event,
            "triggered_by": self.triggered_by,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "next_retry_at": self.next_retry_at,
            "cancel_requested": self.cancel_requested,
            "timeout_seconds": self.timeout_seconds,
        }

        if self.error:
            data["error"] = str(self.error)
            data["error_code"] = self.error.code
            if self.error.details:
                data["error_details"] = self.error.details

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
            user_id=initiator_data.get("user_id"),
        )

        op = Operation(
            operation_id=data["operation_id"],
            op_type=data["type"],
            params=data.get("params", {}),
            initiator=initiator,
            parent_operation_id=data.get("parent_operation_id"),
            retry_count=int(data.get("retry_count", 0) or 0),
            max_retries=int(data.get("max_retries", 2) or 0),
            next_retry_at=data.get("next_retry_at"),
            idempotency_key=data.get("idempotency_key"),
            cancel_requested=bool(data.get("cancel_requested", False)),
            timeout_seconds=data.get("timeout_seconds"),
            correlation_id=data.get("correlation_id"),
            causation_id=data.get("causation_id"),
            source_event=data.get("source_event"),
            triggered_by=data.get("triggered_by", "manual"),
        )

        op.status = _normalize_status(data.get("status", OperationStatus.CREATED.value))
        op.created_at = data.get("created_at", time.time())
        op.started_at = data.get("started_at")
        op.finished_at = data.get("finished_at")
        op.result = data.get("result")

        error_value = data.get("error")
        if error_value:
            if isinstance(error_value, dict):
                error_code = (
                    error_value.get("code")
                    or data.get("error_code")
                    or "execution_error"
                )
                error_message = error_value.get("message") or str(error_value)
                error_details = error_value.get("details") or data.get("error_details")
                op.error = OperationError(
                    code=str(error_code),
                    message=str(error_message),
                    details=error_details,
                )
            else:
                op.error = OperationError(
                    code=str(data.get("error_code") or "execution_error"),
                    message=str(error_value),
                    details=data.get("error_details"),
                )

        return op

class AttemptStatus(str, Enum):
    """Attempt lifecycle statuses (CLAIM + ATTEMPT model)."""

    CREATED = "created"
    CLAIMED = "claimed"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    LOST_CLAIM = "lost_claim"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


@dataclass
class Attempt:
    """
    Attempt entity.

    Operation remains the scheduling/eligibility aggregate; attempt is the execution unit
    guarded by an exclusive claim (lease).
    """

    attempt_id: str
    operation_id: str
    attempt_index: int
    status: AttemptStatus = AttemptStatus.CREATED

    claim_token: Optional[str] = None
    execution_token: Optional[str] = None  # Alias for claim_token (for observability)
    claimed_at: Optional[float] = None
    lease_expires_at: Optional[float] = None
    claimed_by: Optional[str] = None
    worker_id: Optional[str] = None

    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    error: Optional[Dict[str, Any]] = None

    # Attempt execution metadata (causality/observability)
    trigger_type: Optional[str] = None  # initial | retry
    parent_attempt_id: Optional[str] = None
    retry_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "attempt_id": self.attempt_id,
            "operation_id": self.operation_id,
            "attempt_index": self.attempt_index,
            "status": self.status.value,
            "claim_token": self.claim_token,
            "execution_token": self.execution_token,
            "claimed_at": self.claimed_at,
            "lease_expires_at": self.lease_expires_at,
            "claimed_by": self.claimed_by,
            "worker_id": self.worker_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "trigger_type": self.trigger_type,
            "parent_attempt_id": self.parent_attempt_id,
            "retry_reason": self.retry_reason,
        }
        # Keep storage payload small-ish: drop None fields.
        return {k: v for k, v in data.items() if v is not None}

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Attempt":
        status = AttemptStatus(str(data.get("status", AttemptStatus.CREATED.value)))
        return Attempt(
            attempt_id=data["attempt_id"],
            operation_id=data["operation_id"],
            attempt_index=int(data["attempt_index"]),
            status=status,
            claim_token=data.get("claim_token"),
            execution_token=data.get("execution_token"),
            claimed_at=data.get("claimed_at"),
            lease_expires_at=data.get("lease_expires_at"),
            claimed_by=data.get("claimed_by"),
            worker_id=data.get("worker_id"),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
            error=data.get("error"),
            trigger_type=data.get("trigger_type"),
            parent_attempt_id=data.get("parent_attempt_id"),
            retry_reason=data.get("retry_reason"),
        )


# Marker for terminal status
TERMINAL_STATUSES = {
    OperationStatus.COMPLETED,
    OperationStatus.FAILED,
    OperationStatus.CANCELLED,
}


def _normalize_status(value: Any) -> OperationStatus:
    if isinstance(value, OperationStatus):
        return value
    try:
        return OperationStatus(str(value))
    except Exception:
        return OperationStatus.CREATED
