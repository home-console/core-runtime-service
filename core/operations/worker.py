from __future__ import annotations

import asyncio
import importlib
import inspect
import time
import uuid
from typing import Any, Iterable

from core.operations.models import Attempt, AttemptStatus, Operation, OperationStatus, TERMINAL_STATUSES


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

    def _load_hook_stack(self) -> tuple[Any, Any]:
        runtime_dict = getattr(self.runtime, "__dict__", {})
        dispatch = runtime_dict.get("dispatch_system_hooks")
        merge = runtime_dict.get("merge_system_hook_results")
        if callable(dispatch) and callable(merge):
            return dispatch, merge

        module = importlib.import_module("modules.hooks.system")
        return (
            getattr(module, "dispatch_system_hooks"),
            getattr(module, "merge_system_hook_results"),
        )

    def _load_action_stack(self) -> tuple[Any, Any]:
        runtime_dict = getattr(self.runtime, "__dict__", {})
        dispatch = runtime_dict.get("dispatch_execution_action")
        resolve = runtime_dict.get("resolve_execution_actions")
        if callable(dispatch) and callable(resolve):
            return dispatch, resolve

        actions_mod = importlib.import_module("modules.hooks.actions")
        resolver_mod = importlib.import_module("modules.hooks.action_resolver")
        return (
            getattr(actions_mod, "dispatch_action"),
            getattr(resolver_mod, "resolve_actions"),
        )

    async def _dispatch_system_hooks(
        self, hook_name: str, ctx: dict[str, Any]
    ) -> tuple[dict[str, Any], bool, tuple[Any, ...]]:
        dispatch_hooks, merge_hook_results = self._load_hook_stack()
        results = await dispatch_hooks(hook_name, ctx)
        decision = merge_hook_results(results)

        merged_ctx = dict(ctx)
        context_patch = getattr(decision, "context_patch", None)
        if context_patch:
            merged_ctx.update(context_patch)
        return merged_ctx, bool(getattr(decision, "allow", True)), tuple(
            getattr(decision, "actions", ()) or ()
        )

    async def _dispatch_actions(
        self, actions: Iterable[Any], hook_context: dict[str, Any], operation: Operation
    ) -> None:
        dispatch_action, resolve_actions = self._load_action_stack()
        for action in resolve_actions(actions):
            outcome = dispatch_action(
                action,
                {**hook_context, "operation": operation, "now": time.time()},
            )
            if inspect.isawaitable(outcome):
                await outcome

    async def _release_claim(self, storage: Any, attempt_id: str) -> None:
        latest_attempt = await storage.get_attempt(attempt_id)
        if not isinstance(latest_attempt, Attempt):
            return
        latest_attempt.status = AttemptStatus.CREATED
        latest_attempt.claim_token = None
        latest_attempt.execution_token = None
        latest_attempt.claimed_at = None
        latest_attempt.lease_expires_at = None
        latest_attempt.claimed_by = None
        latest_attempt.started_at = None
        latest_attempt.finished_at = None
        latest_attempt.error = None
        await self._persist_attempt(storage, latest_attempt)

    async def _persist_attempt(self, storage: Any, attempt: Attempt) -> None:
        persist_attempt = getattr(storage, "persist_attempt", None)
        if not callable(persist_attempt):
            return
        outcome = persist_attempt(attempt)
        if inspect.isawaitable(outcome):
            await outcome

    async def execute_operation_now(self, operation: Operation) -> Operation:
        now = time.time()

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

        hook_context, allow, actions = await self._dispatch_system_hooks(
            "before_claim", hook_context
        )
        if actions:
            await self._dispatch_actions(actions, hook_context, operation)
            await self.runtime.operations._storage.persist(operation)
            if operation.status in TERMINAL_STATUSES:
                return operation
        if not allow:
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

        attempt = None
        get_attempt = getattr(storage, "get_attempt", None)
        if callable(get_attempt):
            maybe_attempt = get_attempt(attempt_id)
            attempt = await maybe_attempt if inspect.isawaitable(maybe_attempt) else maybe_attempt

        hook_context.update(
            {
                "stage": "before_execute",
                "claim_token": claim_token,
                "execution_token": claim_token,
                "attempt": attempt,
            }
        )
        hook_context, allow, actions = await self._dispatch_system_hooks(
            "before_execute", hook_context
        )
        if actions:
            await self._dispatch_actions(actions, hook_context, operation)
            latest_attempt = hook_context.get("attempt")
            if isinstance(latest_attempt, Attempt):
                await self._persist_attempt(storage, latest_attempt)
            await storage.persist(operation)
            if operation.status in TERMINAL_STATUSES:
                return operation

        if not allow:
            await self._release_claim(storage, attempt_id)
            return operation

        result: Operation = await executor.execute_attempt(attempt_id, claim_token)
        hook_context.update(
            {
                "stage": "on_failure",
                "result": result,
                "operation": result,
                "error": result.error,
            }
        )
        hook_context, _, actions = await self._dispatch_system_hooks(
            "on_failure", hook_context
        )
        if actions:
            await self._dispatch_actions(actions, hook_context, result)
            latest_attempt = hook_context.get("attempt")
            if isinstance(latest_attempt, Attempt):
                await self._persist_attempt(storage, latest_attempt)

        hook_context.update(
            {
                "stage": "after_execute",
                "result": result,
                "operation": result,
            }
        )
        hook_context, _, actions = await self._dispatch_system_hooks(
            "after_execute", hook_context
        )
        if actions:
            await self._dispatch_actions(actions, hook_context, result)
            latest_attempt = hook_context.get("attempt")
            if isinstance(latest_attempt, Attempt):
                await self._persist_attempt(storage, latest_attempt)

        await storage.persist(result)
        return result

    async def tick(self):
        created_ops = await self.runtime.operations.list(limit=1000, status="created")
        failed_ops = await self.runtime.operations.list(limit=1000, status="failed")
        ops = list(created_ops) + list(failed_ops)
        for op in ops:
            if op.status in (OperationStatus.CREATED, OperationStatus.FAILED):
                await self.execute_operation_now(op)
