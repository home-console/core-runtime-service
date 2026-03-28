from __future__ import annotations

import asyncio
import inspect
import time
import uuid
from typing import Any, Iterable, cast

from core.operations.models import TERMINAL_STATUSES, Attempt, AttemptStatus, Operation
from core.operations.runtime_contract import (
    HookDecision,
    NoopActionDispatcher,
    NoopExecutionHooks,
    NoopOperationSource,
    OperationSource,
    PassThroughActionResolver,
)

_NOOP_HOOKS = NoopExecutionHooks()
_NOOP_ACTION_DISPATCHER = NoopActionDispatcher()
_PASS_THROUGH_ACTION_RESOLVER = PassThroughActionResolver()
_NOOP_OPERATION_SOURCE = NoopOperationSource()


class OperationWorker:
    def __init__(self, runtime: Any):
        self.runtime = runtime
        self.running = False
        self._task: asyncio.Task[Any] | None = None
        self.worker_id = f"worker-{id(self)}-{uuid.uuid4().hex[:8]}"
        self._event_subscription_active = False

    async def start(self):
        self.running = True
        if self._task is None:
            self._task = asyncio.current_task()
        await self._subscribe_operation_events()
        await self._replay_unprocessed_events()
        try:
            while self.running:
                await self.tick()
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        finally:
            await self._unsubscribe_operation_events()
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

    def _resolve_hooks(self) -> Any:
        runtime_dict = getattr(self.runtime, "__dict__", {})
        hooks = runtime_dict.get("hooks")
        if hooks is not None and callable(getattr(hooks, "run", None)):
            return hooks
        return _NOOP_HOOKS

    def _resolve_action_dispatcher(self) -> Any:
        runtime_dict = getattr(self.runtime, "__dict__", {})
        dispatcher = runtime_dict.get("action_dispatcher")
        if dispatcher is not None and callable(getattr(dispatcher, "dispatch", None)):
            return dispatcher
        return _NOOP_ACTION_DISPATCHER

    def _resolve_action_resolver(self) -> Any:
        runtime_dict = getattr(self.runtime, "__dict__", {})
        resolver = runtime_dict.get("action_resolver")
        if resolver is not None and callable(getattr(resolver, "resolve", None)):
            return resolver
        return _PASS_THROUGH_ACTION_RESOLVER

    def _resolve_operation_source(self) -> OperationSource:
        runtime_dict = getattr(self.runtime, "__dict__", {})
        source = runtime_dict.get("operation_source")
        if source is not None and callable(getattr(source, "get_runnable", None)):
            return source
        return _NOOP_OPERATION_SOURCE

    def _resolve_event_bus(self) -> Any:
        runtime_dict = getattr(self.runtime, "__dict__", {})
        event_bus = runtime_dict.get("event_bus")
        if event_bus is not None and callable(getattr(event_bus, "subscribe", None)):
            return event_bus
        return None

    async def _subscribe_operation_events(self) -> None:
        if self._event_subscription_active:
            return
        event_bus = self._resolve_event_bus()
        if event_bus is None:
            return
        outcome = event_bus.subscribe("operation_ready", self._on_event)
        if inspect.isawaitable(outcome):
            await outcome
        self._event_subscription_active = True

    async def _unsubscribe_operation_events(self) -> None:
        if not self._event_subscription_active:
            return
        event_bus = self._resolve_event_bus()
        if event_bus is None:
            self._event_subscription_active = False
            return
        unsubscribe = getattr(event_bus, "unsubscribe", None)
        if callable(unsubscribe):
            outcome = unsubscribe("operation_ready", self._on_event)
            if inspect.isawaitable(outcome):
                await outcome
        self._event_subscription_active = False

    async def _replay_unprocessed_events(self) -> None:
        event_bus = self._resolve_event_bus()
        if event_bus is None:
            return
        get_unprocessed_events = getattr(event_bus, "get_unprocessed_events", None)
        if not callable(get_unprocessed_events):
            return

        events_outcome = get_unprocessed_events()
        events = await events_outcome if inspect.isawaitable(events_outcome) else events_outcome
        if not isinstance(events, list):
            return
        events_list = cast(list[Any], events)
        for event in events_list:
            if not isinstance(event, dict):
                continue
            await self._on_event(event)

    async def _mark_event_processed(self, event_id: str) -> None:
        event_bus = self._resolve_event_bus()
        if event_bus is None:
            return
        mark = getattr(event_bus, "mark_event_processed", None)
        if not callable(mark):
            return
        outcome = mark(event_id)
        if inspect.isawaitable(outcome):
            await outcome

    async def _is_event_processed(self, event_id: str) -> bool:
        event_bus = self._resolve_event_bus()
        if event_bus is None:
            return False
        is_processed = getattr(event_bus, "is_event_processed", None)
        if not callable(is_processed):
            return False
        outcome = is_processed(event_id)
        value = await outcome if inspect.isawaitable(outcome) else outcome
        return bool(value)

    async def _claim_event(self, event_id: str) -> bool:
        event_bus = self._resolve_event_bus()
        if event_bus is None:
            return True
        claim = getattr(event_bus, "claim_event", None)
        if not callable(claim):
            return True
        outcome = claim(event_id, self.worker_id)
        value = await outcome if inspect.isawaitable(outcome) else outcome
        return bool(value)

    async def _on_event(self, event_type: Any, data: Any | None = None) -> None:
        payload: dict[str, Any]
        resolved_type: Any
        if isinstance(event_type, dict) and data is None:
            payload = cast(dict[str, Any], event_type)
            resolved_type = payload.get("type")
        else:
            payload = cast(dict[str, Any], data) if isinstance(data, dict) else {}
            resolved_type = event_type if isinstance(event_type, str) else ""

        if resolved_type != "operation_ready":
            return

        operation_id = payload.get("operation_id")
        event_id = payload.get("id")
        if not operation_id:
            return

        if event_id and await self._is_event_processed(str(event_id)):
            return
        if event_id and not await self._claim_event(str(event_id)):
            return

        operation = await self.runtime.operations.get(str(operation_id))
        if operation is None:
            return

        try:
            await self.execute_operation_now(operation)
            if event_id:
                await self._mark_event_processed(str(event_id))
        except Exception:
            # at-least-once: keep event unacked so replay can retry later
            raise

    def _normalize_hook_decision(
        self,
        decision: Any,
        ctx: dict[str, Any],
    ) -> tuple[dict[str, Any], bool, tuple[Any, ...]]:
        if isinstance(decision, HookDecision):
            return (
                dict(decision.context),
                bool(decision.allow),
                tuple(decision.actions or ()),
            )

        if (
            isinstance(decision, tuple)
            and len(decision) == 3
            and isinstance(decision[0], dict)
        ):
            merged_ctx, allow, actions = decision
            return dict(merged_ctx), bool(allow), tuple(actions or ())

        if isinstance(decision, dict):
            merged_ctx = dict(ctx)
            context_patch = decision.get("context_patch")
            if isinstance(context_patch, dict):
                merged_ctx.update(context_patch)
            allow = bool(decision.get("allow", True))
            actions = tuple(decision.get("actions") or ())
            return merged_ctx, allow, actions

        return dict(ctx), True, ()

    async def _dispatch_system_hooks(
        self, hook_name: str, ctx: dict[str, Any]
    ) -> tuple[dict[str, Any], bool, tuple[Any, ...]]:
        hooks = self._resolve_hooks()
        outcome = hooks.run(hook_name, ctx)
        if inspect.isawaitable(outcome):
            outcome = await outcome
        return self._normalize_hook_decision(outcome, ctx)

    async def _dispatch_actions(
        self, actions: Iterable[Any], hook_context: dict[str, Any], operation: Operation
    ) -> None:
        dispatcher = self._resolve_action_dispatcher()
        resolver = self._resolve_action_resolver()
        for action in resolver.resolve(actions):
            outcome = dispatcher.dispatch(
                action, {**hook_context, "operation": operation, "now": time.time()}
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
            "runtime": self.runtime,
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
            attempt = (
                await maybe_attempt
                if inspect.isawaitable(maybe_attempt)
                else maybe_attempt
            )

        hook_context.update(
            {
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
        source = self._resolve_operation_source()
        ops = await source.get_runnable()
        for op in ops:
            await self.execute_operation_now(op)
