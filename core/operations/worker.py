import asyncio
import time
import uuid
from typing import Any

from modules.hooks.actions import dispatch_action
from modules.hooks.system import dispatch_system_hooks, merge_system_hook_results

from core.operations.models import (
    AttemptStatus,
    Operation,
    OperationError,
    OperationStatus,
)


class OperationWorker:
    def __init__(self, runtime: Any):
        self.runtime = runtime
        self.running = False
        self._task: asyncio.Task[Any] | None = None
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

    async def _dispatch_system_hooks(
        self, hook_name: str, ctx: dict[str, Any]
    ) -> tuple[dict[str, Any], bool, tuple[Any, ...]]:
        results = await dispatch_system_hooks(hook_name, ctx)
        decision = merge_system_hook_results(results)
        merged_ctx = dict(ctx)
        if decision.context_patch:
            merged_ctx.update(decision.context_patch)
        return merged_ctx, decision.allow, decision.actions

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

        hook_context: dict[str, Any] = {
            "stage": "before_claim",
            "worker_id": self.worker_id,
            "now": now,
            "operation": operation,
            "operation_id": operation.operation_id,
            "operation_type": operation.type,
            "retry_count": operation.retry_count,
            "max_retries": operation.max_retries,
            "attempt_id": attempt_id,
            "attempt_index": attempt_index,
            "lease_ttl_s": lease_ttl_s,
        }

        hook_context, allow, _ = await self._dispatch_system_hooks(
            "before_claim", hook_context
        )
        if not allow:
            operation.status = OperationStatus.FAILED
            operation.error = OperationError(
                code="hook_blocked",
                message="before_claim system hook blocked execution",
                details={"hook_name": "before_claim"},
            )
            operation.finished_at = now
            await self.runtime.operations._storage.persist(operation)
            return operation

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

        hook_context.update(
            {
                "stage": "before_execute",
                "claim_token": claim_token,
            }
        )
        hook_context, allow, _ = await self._dispatch_system_hooks(
            "before_execute", hook_context
        )
        if not allow:
            latest_attempt = await storage.get_attempt(attempt_id)
            if latest_attempt is not None:
                latest_attempt.status = AttemptStatus.FAILED
                latest_attempt.finished_at = time.time()
                latest_attempt.error = {
                    "code": "hook_blocked",
                    "message": "before_execute system hook blocked execution",
                }
                await storage.persist_attempt(latest_attempt)

            operation.status = OperationStatus.FAILED
            operation.error = OperationError(
                code="hook_blocked",
                message="before_execute system hook blocked execution",
                details={"hook_name": "before_execute"},
            )
            operation.finished_at = time.time()
            await storage.persist(operation)
            return operation

        res: Operation = await executor.execute_attempt(attempt_id, claim_token)

        if res.status == OperationStatus.FAILED:
            hook_context.update(
                {
                    "stage": "on_failure",
                    "operation": res,
                    "result": res,
                    "error": res.error,
                }
            )
            hook_context, allow, actions = await self._dispatch_system_hooks(
                "on_failure", hook_context
            )
            if allow and actions:
                for action in actions:
                    await dispatch_action(
                        action,
                        {**hook_context, "operation": res, "now": time.time()},
                    )
        else:
            hook_context.update(
                {
                    "stage": "after_execute",
                    "result": res,
                }
            )
            _, allow, actions = await self._dispatch_system_hooks(
                "after_execute", hook_context
            )
            if allow and actions:
                for action in actions:
                    await dispatch_action(
                        action,
                        {**hook_context, "operation": res, "now": time.time()},
                    )
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
                if op.next_retry_at is None or now < op.next_retry_at:
                    continue
                await self.execute_operation_now(op)
