"""
OperationStorage - персистентность операций.

Отвечает за сохранение и загрузку операций из storage.
"""

import time
import uuid
from typing import Optional, List, Any, Tuple

from core.operations.models import (
    Attempt,
    AttemptStatus,
    Operation,
    OperationInitiator,
)


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
        operation_id = f"op-{uuid.uuid4().hex[:12]}"

        # Causality/observability metadata may be injected by event->operation bridges
        # (e.g. automation handlers). Execution flow MUST NOT depend on these fields.
        correlation_id = params.get("correlation_id")
        causation_id = params.get("causation_id")
        # If event_id is provided, prefer it. Otherwise keep legacy "source_event" value.
        source_event = params.get("event_id") or params.get("source_event")
        triggered_by = params.get("triggered_by")
        if not triggered_by:
            # Best-effort heuristic: if the caller provided any event-like metadata → 'event'.
            triggered_by = "event" if (params.get("event_id") or params.get("source_event") or "raw" in params) else "manual"

        idempotency_key = params.get("idempotency_key")
        
        operation = Operation(
            operation_id=operation_id,
            op_type=op_type,
            params=params,
            initiator=initiator,
            parent_operation_id=parent_operation_id,
            retry_count=retry_count,
            max_retries=max_retries,
            next_retry_at=next_retry_at,
            idempotency_key=idempotency_key,
            cancel_requested=bool(params.get("cancel_requested", False)),
            timeout_seconds=params.get("timeout_seconds"),
            correlation_id=correlation_id,
            causation_id=causation_id,
            source_event=source_event,
            triggered_by=triggered_by,
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

    async def get_attempts(self, operation_id: str) -> List[Attempt]:
        """
        Return ordered attempt history for an operation (by attempt_index asc).
        """
        keys = await self.runtime.storage.list_keys("operation_attempts")
        attempts: List[Attempt] = []
        for key in keys:
            try:
                data = await self.runtime.storage.get("operation_attempts", key)
                if not data:
                    continue
                if data.get("operation_id") != operation_id:
                    continue
                attempts.append(Attempt.from_dict(data))
            except Exception:
                continue

        attempts.sort(key=lambda a: a.attempt_index)
        return attempts

    # ===================== ATTEMPTS (CLAIM + ATTEMPT model) =====================

    async def ensure_attempt_created(
        self, attempt_id: str, operation_id: str, attempt_index: int
    ) -> Attempt:
        """
        Ensure an attempt record exists with status='created'.

        Idempotent: if the attempt already exists, returns it as-is.
        """

        attempt: Optional[Attempt] = None

        async with self.runtime.storage.transaction():
            existing = await self.runtime.storage.get("operation_attempts", attempt_id)
            if existing is not None:
                attempt = Attempt.from_dict(existing)
                return attempt

            trigger_type = "initial" if int(attempt_index) == 0 else "retry"
            parent_attempt_id = (
                f"attempt-{operation_id}-i{attempt_index - 1}"
                if int(attempt_index) > 0
                else None
            )
            retry_reason = None
            if int(attempt_index) > 0:
                try:
                    op_data = await self.runtime.storage.get("operations", operation_id)
                    if isinstance(op_data, dict):
                        op = Operation.from_dict(op_data)
                        retry_reason = op.error.code if op.error else None
                except Exception:
                    retry_reason = None

            attempt = Attempt(
                attempt_id=attempt_id,
                operation_id=operation_id,
                attempt_index=attempt_index,
                status=AttemptStatus.CREATED,
                trigger_type=trigger_type,
                parent_attempt_id=parent_attempt_id,
                retry_reason=retry_reason,
            )
            await self.runtime.storage.set("operation_attempts", attempt_id, attempt.to_dict())

        return attempt  # type: ignore[return-value]

    async def get_attempt(self, attempt_id: str) -> Optional[Attempt]:
        data = await self.runtime.storage.get("operation_attempts", attempt_id)
        if data is None:
            return None
        return Attempt.from_dict(data)

    async def persist_attempt(self, attempt: Attempt) -> None:
        await self.runtime.storage.set(
            "operation_attempts", attempt.attempt_id, attempt.to_dict()
        )

    async def try_claim_attempt(
        self, attempt_id: str, worker_id: str, lease_ttl: int
    ) -> Tuple[bool, Optional[str]]:
        """
        Atomically claim an attempt using a lease.

        Claim succeeds only if:
        - attempt.status is not terminal (created/claimed)
        - claim_token is absent OR previous lease is expired
        """

        now = time.time()
        async with self.runtime.storage.transaction():
            data = await self.runtime.storage.get("operation_attempts", attempt_id)
            if data is None:
                return False, None

            attempt = Attempt.from_dict(data)

            if attempt.status not in (
                AttemptStatus.CREATED,
                AttemptStatus.CLAIMED,
                AttemptStatus.LOST_CLAIM,
            ):
                return False, None

            claim_absent = attempt.claim_token is None
            lease_expired = (
                attempt.lease_expires_at is None or attempt.lease_expires_at < now
            )

            if not (claim_absent or lease_expired):
                return False, None

            claim_token = uuid.uuid4().hex
            attempt.status = AttemptStatus.CLAIMED
            attempt.claim_token = claim_token
            attempt.execution_token = claim_token
            attempt.claimed_at = now
            attempt.lease_expires_at = now + float(lease_ttl)
            attempt.claimed_by = worker_id
            attempt.worker_id = worker_id
            await self.runtime.storage.set("operation_attempts", attempt_id, attempt.to_dict())

        return True, claim_token

    async def extend_claim(
        self, attempt_id: str, claim_token: str, lease_ttl: int
    ) -> bool:
        """
        Extend an existing claim lease.

        Returns True if and only if:
        - attempt exists
        - attempt.claim_token matches claim_token

        Does not change attempt status; only moves lease_expires_at forward.
        """

        now = time.time()
        async with self.runtime.storage.transaction():
            data = await self.runtime.storage.get(
                "operation_attempts", attempt_id
            )
            if data is None:
                return False

            attempt = Attempt.from_dict(data)
            if attempt.claim_token != claim_token:
                return False

            attempt.lease_expires_at = now + float(lease_ttl)
            await self.runtime.storage.set(
                "operation_attempts", attempt_id, attempt.to_dict()
            )
            return True
