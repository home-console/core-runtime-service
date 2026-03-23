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
        
        operation = Operation(
            operation_id=operation_id,
            op_type=op_type,
            params=params,
            initiator=initiator,
            parent_operation_id=parent_operation_id,
            retry_count=retry_count,
            max_retries=max_retries,
            next_retry_at=next_retry_at,
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

    # ===================== ATTEMPTS (CLAIM + ATTEMPT model) =====================

    async def ensure_attempt_created(
        self, attempt_id: str, operation_id: str, attempt_index: int
    ) -> Attempt:
        """
        Ensure an attempt record exists with status='created'.

        Idempotent: if the attempt already exists, returns it as-is.
        """

        async with self.runtime.storage.transaction():
            existing = await self.runtime.storage.get(
                "operation_attempts", attempt_id
            )
            if existing is not None:
                return Attempt.from_dict(existing)

            attempt = Attempt(
                attempt_id=attempt_id,
                operation_id=operation_id,
                attempt_index=attempt_index,
                status=AttemptStatus.CREATED,
            )
            await self.runtime.storage.set(
                "operation_attempts", attempt_id, attempt.to_dict()
            )
            return attempt

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

            if attempt.status not in (AttemptStatus.CREATED, AttemptStatus.CLAIMED):
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
            attempt.claimed_at = now
            attempt.lease_expires_at = now + float(lease_ttl)
            attempt.claimed_by = worker_id

            await self.runtime.storage.set("operation_attempts", attempt_id, attempt.to_dict())
            return True, claim_token
