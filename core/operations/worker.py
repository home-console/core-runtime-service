import asyncio
import time
import uuid
from typing import Any

from core.operations.models import RETRYABLE_ERRORS, Operation, OperationStatus
from core.logger_helper import info


class OperationWorker:
    def __init__(self, runtime: Any):
        self.runtime = runtime
        self.running = False
        self._task: asyncio.Task | None = None
        self.worker_id = f"worker-{id(self)}-{uuid.uuid4().hex[:8]}"

    async def start(self):
        self.running = True
        if self._task is None:
            self._task = asyncio.current_task()
        try:
            while self.running:
                await self.tick()
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        finally:
            self.running = False

    async def stop(self) -> None:
        self.running = False
        if self._task is None or self._task is asyncio.current_task():
            return
        if not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    def _apply_retry_policy_after_failure(self, operation: Operation, now: float) -> None:
        """
        Scheduler-side retry policy.

        Executor must not decide retry; worker applies backoff and mutates operation metadata
        for the next attempt eligibility window.
        """
        if (
            operation.error
            and operation.error.code in RETRYABLE_ERRORS
            and operation.retry_count < operation.max_retries
        ):
            delay_seconds = 2 ** operation.retry_count
            operation.retry_count += 1
            operation.next_retry_at = now + delay_seconds
            # Scheduler-side observability: execution ownership stays with worker.
            # Logging is best-effort; must not affect flow.
            try:
                # This method is sync; we enqueue a log task.
                import asyncio as _asyncio
                _asyncio.create_task(
                    info(
                        self.runtime,
                        "retry scheduled",
                        operation_id=operation.operation_id,
                        retry_count=operation.retry_count,
                        next_retry_at=operation.next_retry_at,
                        error_code=operation.error.code if operation.error else None,
                    )
                )
            except Exception:
                pass
        else:
            operation.next_retry_at = None

    async def execute_operation_now(self, operation: Operation) -> Operation:
        """
        Inline execution path using CLAIM + ATTEMPT.

        Used by OperationManager as a thin delegate for backward compatibility.
        """

        now = time.time()

        # Eligibility gating: executor is attempt-only; worker decides if attempt should be started.
        if operation.status == OperationStatus.CREATED:
            if operation.next_retry_at is not None and now < operation.next_retry_at:
                return operation
        elif operation.status == OperationStatus.FAILED:
            if not operation.can_retry(now):
                return operation

        attempt_index = int(operation.retry_count or 0)
        attempt_id = f"attempt-{operation.operation_id}-i{attempt_index}"

        lease_ttl_raw = getattr(self.runtime, "operation_attempt_lease_ttl", 30)
        try:
            lease_ttl_s = int(lease_ttl_raw)
        except Exception:
            lease_ttl_s = 30

        storage = self.runtime.operations._storage
        executor = self.runtime.operations._executor

        await storage.ensure_attempt_created(
            attempt_id=attempt_id,
            operation_id=operation.operation_id,
            attempt_index=attempt_index,
        )

        ok, claim_token = await storage.try_claim_attempt(
            attempt_id=attempt_id, worker_id=self.worker_id, lease_ttl=lease_ttl_s
        )
        if not ok or not claim_token:
            return operation

        res: Operation = await executor.execute_attempt(attempt_id, claim_token)

        # Retry metadata is scheduler-side.
        if res.status == OperationStatus.FAILED:
            self._apply_retry_policy_after_failure(res, now)
        else:
            res.next_retry_at = None

        await storage.persist(res)
        return res

    async def tick(self):
        now = time.time()

        created_ops = await self.runtime.operations.list(limit=1000, status="created")
        failed_ops = await self.runtime.operations.list(limit=1000, status="failed")

        ops = list(created_ops) + list(failed_ops)

        for op in ops:
            if op.status == OperationStatus.CREATED:
                if op.next_retry_at is not None and now < op.next_retry_at:
                    continue
                await self.execute_operation_now(op)
                continue

            if op.status == OperationStatus.FAILED:
                if not op.can_retry(now):
                    continue
                await self.execute_operation_now(op)