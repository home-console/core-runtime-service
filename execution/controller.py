"""
Execution controller (D3).

Controller:
- не знает домены
- не знает плагины (кроме optional metadata)
- не знает automation
- работает только с operation envelope + policy + backend registry
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Protocol
from uuid import uuid4
from datetime import datetime, UTC
import time
import asyncio

from .backend import BackendId, ExecutionBackend, InProcessBackend, ProcessBackend, ContainerBackend, OperationResult
from .policy import ExecutionPolicy, StateExecutionPolicy
from .trace import ExecutionTrace, ExecutionStatus, make_execution_namespace_keys


class ExecutionController(Protocol):
    async def execute_operation(
        self,
        operation_id: str,
        operation_type: str,
        params: dict,
        context: dict,
    ) -> OperationResult: ...


class ExecutionControllerImpl:
    def __init__(
        self,
        runtime: Any,
        policy: Optional[ExecutionPolicy] = None,
        backends: Optional[Dict[BackendId, ExecutionBackend]] = None,
        *,
        policy_storage_namespace: str = "execution",
        policy_storage_key: str = "policy",
    ):
        self._runtime = runtime
        self._policy = policy or StateExecutionPolicy(runtime)
        self._policy_ns = policy_storage_namespace
        self._policy_key = policy_storage_key

        self._backends: Dict[BackendId, ExecutionBackend] = backends or {
            "in_process": InProcessBackend(runtime),
            "process": ProcessBackend(),
            "container": ContainerBackend(),
        }

        # Конфигурация observability (можно сделать настраиваемой позднее)
        self._stderr_tail_max_chars: int = 4000
        # Простой счетчик для ограничений concurrency (D3.4)
        self._running: int = 0
        self._running_lock = asyncio.Lock()

    async def _load_policy(self) -> Dict[str, Any]:
        """
        Загружает декларативный policy из storage, чтобы можно было менять без рестарта.
        """
        try:
            storage = getattr(self._runtime, "storage", None)
            if storage is None:
                return {}
            raw = await storage.get(self._policy_ns, self._policy_key)
            if isinstance(raw, dict):
                return raw
        except Exception:
            pass
        return {}

    def _generate_execution_id(self) -> str:
        """
        Генерирует уникальный execution_id для одной попытки исполнения операции.

        Важно: execution_id ≠ operation_id. Одна операция может иметь несколько execution'ов.
        """
        return f"exec-{uuid4().hex[:12]}"

    async def _load_execution_trace(self, execution_id: str) -> Optional[ExecutionTrace]:
        storage = getattr(self._runtime, "storage", None)
        if storage is None:
            return None
        try:
            keys = make_execution_namespace_keys("", execution_id)
            data = await storage.get("execution", keys["trace_key"])
            if isinstance(data, dict):
                # operation_id внутри trace, поэтому operation_id в keys здесь не нужен
                return ExecutionTrace.from_dict(data)
        except Exception:
            return None
        return None

    async def on_execution_start(self, trace: ExecutionTrace) -> None:
        """
        Lifecycle hook: фиксируем старт исполнения.

        - Записываем trace со status=\"running\" в namespace storage/execution
        - Пишем индекс по operation_id
        - Эмитим execution.started (best-effort)
        """
        storage = getattr(self._runtime, "storage", None)
        if storage is not None:
            try:
                keys = make_execution_namespace_keys(trace.operation_id, trace.execution_id)
                await storage.set("execution", keys["trace_key"], trace.to_dict())
                await storage.set(
                    "execution",
                    keys["index_key"],
                    {
                        "execution_id": trace.execution_id,
                        "operation_id": trace.operation_id,
                        "operation_type": trace.operation_type,
                        "backend": trace.backend,
                        "status": trace.status,
                        "started_at": trace.started_at.isoformat(),
                        "finished_at": trace.finished_at.isoformat() if trace.finished_at else None,
                        "duration_ms": trace.duration_ms,
                        "parent_execution_id": trace.parent_execution_id,
                        "retry_index": trace.retry_index,
                    },
                )
                # Lineage index (by_parent) — только если есть родитель
                if trace.parent_execution_id:
                    parent_key = f"by_parent/{trace.parent_execution_id}/{trace.execution_id}"
                    await storage.set(
                        "execution",
                        parent_key,
                        {
                            "execution_id": trace.execution_id,
                            "operation_id": trace.operation_id,
                            "operation_type": trace.operation_type,
                            "backend": trace.backend,
                            "status": trace.status,
                            "started_at": trace.started_at.isoformat(),
                            "finished_at": trace.finished_at.isoformat() if trace.finished_at else None,
                            "duration_ms": trace.duration_ms,
                            "retry_index": trace.retry_index,
                        },
                    )
            except Exception:
                # Observability не должен ломать execution
                pass

        # Events (optional, best-effort)
        event_bus = getattr(self._runtime, "event_bus", None)
        if event_bus is not None and hasattr(event_bus, "publish"):
            try:
                await event_bus.publish(
                    "execution.started",
                    {
                        "execution_id": trace.execution_id,
                        "operation_id": trace.operation_id,
                        "backend": trace.backend,
                        "status": trace.status,
                    },
                )
            except Exception:
                pass

    async def on_execution_finish(self, trace: ExecutionTrace) -> None:
        """
        Lifecycle hook: фиксируем завершение исполнения.

        - Обновляем trace (status, finished_at, duration_ms, error_*)
        - Обновляем индекс по operation_id
        - Эмитим execution.finished (best-effort)
        """
        storage = getattr(self._runtime, "storage", None)
        if storage is not None:
            try:
                keys = make_execution_namespace_keys(trace.operation_id, trace.execution_id)
                await storage.set("execution", keys["trace_key"], trace.to_dict())
                await storage.set(
                    "execution",
                    keys["index_key"],
                    {
                        "execution_id": trace.execution_id,
                        "operation_id": trace.operation_id,
                        "operation_type": trace.operation_type,
                        "backend": trace.backend,
                        "status": trace.status,
                        "started_at": trace.started_at.isoformat(),
                        "finished_at": trace.finished_at.isoformat() if trace.finished_at else None,
                        "duration_ms": trace.duration_ms,
                        "parent_execution_id": trace.parent_execution_id,
                        "retry_index": trace.retry_index,
                    },
                )
                if trace.parent_execution_id:
                    parent_key = f"by_parent/{trace.parent_execution_id}/{trace.execution_id}"
                    await storage.set(
                        "execution",
                        parent_key,
                        {
                            "execution_id": trace.execution_id,
                            "operation_id": trace.operation_id,
                            "operation_type": trace.operation_type,
                            "backend": trace.backend,
                            "status": trace.status,
                            "started_at": trace.started_at.isoformat(),
                            "finished_at": trace.finished_at.isoformat() if trace.finished_at else None,
                            "duration_ms": trace.duration_ms,
                            "retry_index": trace.retry_index,
                        },
                    )
            except Exception:
                pass

        event_bus = getattr(self._runtime, "event_bus", None)
        if event_bus is not None and hasattr(event_bus, "publish"):
            try:
                await event_bus.publish(
                    "execution.finished",
                    {
                        "execution_id": trace.execution_id,
                        "operation_id": trace.operation_id,
                        "backend": trace.backend,
                        "status": trace.status,
                    },
                )
            except Exception:
                pass

    def _map_status_from_result(self, res: OperationResult) -> ExecutionStatus:
        if res.ok:
            return "ok"
        if getattr(res, "timed_out", False):
            return "timeout"
        if getattr(res, "killed", False):
            return "killed"

        err = res.error or {}
        code = err.get("code")
        if code == "timeout":
            return "timeout"
        if code == "cancelled":
            return "cancelled"
        return "error"

    def _extract_error_fields(self, res: OperationResult) -> Dict[str, Optional[str]]:
        if res.ok or not res.error:
            return {"code": None, "message": None}

        err = res.error
        code = err.get("code")
        message = err.get("message")
        return {"code": str(code) if code is not None else None, "message": str(message) if message is not None else None}

    def _extract_stderr_tail(self, res: OperationResult) -> Optional[str]:
        stderr = getattr(res, "stderr", None)
        if not stderr:
            # fallback: иногда stderr лежит в error.details.stderr
            try:
                details = (res.error or {}).get("details") or {}
                if isinstance(details, dict):
                    stderr = details.get("stderr")
            except Exception:
                stderr = None

        if not stderr or not isinstance(stderr, str):
            return None
        if len(stderr) <= self._stderr_tail_max_chars:
            return stderr
        return stderr[-self._stderr_tail_max_chars :]

    async def execute_operation(
        self,
        operation_id: str,
        operation_type: str,
        params: dict,
        context: dict,
    ) -> OperationResult:
        # controller не должен делать доменные вызовы; только policy+backend+observability
        policy_dict = await self._load_policy()

        metadata: Dict[str, Any] = {
            "_execution_policy": policy_dict,
        }

        plugin_name = None
        try:
            plugin_name = (context or {}).get("plugin_name")
        except Exception:
            plugin_name = None

        backend_id = self._policy.select_backend(operation_type, plugin_name, metadata)
        backend = self._backends.get(backend_id)
        if backend is None:
            return OperationResult(
                ok=False,
                error={"code": "unknown_backend", "message": f"Unknown backend: {backend_id}"},
                backend=str(backend_id),
            )

        # Лимиты concurrency (D3.4). Для служебных операций (execution.*) не применяем.
        limits = (policy_dict.get("limits") or {}) if isinstance(policy_dict, dict) else {}
        max_running = limits.get("max_running")
        # Lineage / overrides (для retry/replay)
        parent_execution_id = (context or {}).get("_parent_execution_id")
        retry_index_raw = (context or {}).get("_retry_index")
        try:
            retry_index = int(retry_index_raw) if retry_index_raw is not None else 0
        except (TypeError, ValueError):
            retry_index = 0

        forced_execution_id = (context or {}).get("_execution_id_override")
        execution_id = forced_execution_id or self._generate_execution_id()

        if not operation_type.startswith("execution.") and isinstance(max_running, int):
            async with self._running_lock:
                if max_running <= 0 or self._running >= max_running:
                    # Не стартуем execution, сразу фиксируем ошибку.
                    now = datetime.now(UTC)
                    trace = ExecutionTrace(
                        execution_id=execution_id,
                        operation_id=operation_id,
                        operation_type=operation_type,
                        backend=backend_id,
                        status="error",
                        started_at=now,
                        finished_at=now,
                        duration_ms=0,
                        error_code="execution_limit_exceeded",
                        error_message="Execution concurrency limit exceeded",
                        stderr_tail=None,
                    )
                    await self.on_execution_finish(trace)
                    return OperationResult(
                        ok=False,
                        error={
                            "code": "execution_limit_exceeded",
                            "message": "Execution concurrency limit exceeded",
                        },
                        backend=str(backend_id),
                    )
                self._running += 1
        else:
            async with self._running_lock:
                self._running += 1

        started_at_dt = datetime.now(UTC)
        started_monotonic = time.monotonic()

        trace = ExecutionTrace(
            execution_id=execution_id,
            operation_id=operation_id,
            operation_type=operation_type,
            backend=backend_id,
            status="running",
            started_at=started_at_dt,
            finished_at=None,
            duration_ms=None,
            error_code=None,
            error_message=None,
            stderr_tail=None,
            parent_execution_id=parent_execution_id,
            retry_index=retry_index,
        )

        # Сохраняем envelope для последующих retry/replay (D3.5).
        storage = getattr(self._runtime, "storage", None)
        if storage is not None:
            try:
                replay_ctx = {
                    "request_id": (context or {}).get("request_id"),
                    "caller": (context or {}).get("caller"),
                    "metadata": (context or {}).get("metadata") if isinstance((context or {}).get("metadata"), dict) else {},
                }
                await storage.set(
                    "execution",
                    f"envelopes/{execution_id}",
                    {
                        "operation_type": operation_type,
                        "params": params or {},
                        "context": replay_ctx,
                    },
                )
            except Exception:
                pass

        await self.on_execution_start(trace)

        # Backend работает только с envelope операции (operation_type/params/context).
        # Policy dict прокидываем через context, чтобы backend мог (опционально) читать свои настройки,
        # не делая запросов к storage и не ломая границы слоёв.
        ctx = dict(context or {})
        ctx.setdefault("operation_id", operation_id)
        ctx.setdefault("_execution_policy", policy_dict)
        ctx.setdefault("execution_id", execution_id)

        try:
            try:
                res = await backend.execute(
                    operation_type=operation_type,
                    params=params or {},
                    context=ctx,
                    timeout=None,
                )
            except Exception as e:
                # Любая ошибка бэкенда тоже должна отражаться в трассе
                finished_at_dt = datetime.now(UTC)
                duration_ms = int((time.monotonic() - started_monotonic) * 1000)
                trace.status = "error"
                trace.finished_at = finished_at_dt
                trace.duration_ms = duration_ms
                trace.error_code = "backend_exception"
                trace.error_message = str(e)
                trace.stderr_tail = None
                await self.on_execution_finish(trace)

                return OperationResult(
                    ok=False,
                    error={"code": "backend_exception", "message": str(e), "type": type(e).__name__},
                    backend=str(backend_id),
                )

            # Успешное завершение backend'а (ok или ошибка уровня исполнения)
            finished_at_dt = datetime.now(UTC)
            duration_ms = int((time.monotonic() - started_monotonic) * 1000)

            status: ExecutionStatus = self._map_status_from_result(res)
            err_fields = self._extract_error_fields(res)
            stderr_tail = self._extract_stderr_tail(res)

            # Если до этого был вызван cancel_execution и trace уже помечен как cancelled,
            # сохраняем cancel-маркеры (cancelled_at/cancel_reason).
            try:
                existing = await self._load_execution_trace(execution_id)
            except Exception:
                existing = None

            if existing is not None and existing.cancelled_at is not None:
                trace.cancelled_at = existing.cancelled_at
                trace.cancel_reason = existing.cancel_reason
                if existing.status == "cancelled":
                    status = "cancelled"

            trace.status = status
            trace.finished_at = finished_at_dt
            trace.duration_ms = duration_ms
            trace.error_code = err_fields["code"]
            trace.error_message = err_fields["message"]
            trace.stderr_tail = stderr_tail

            await self.on_execution_finish(trace)

            return res
        finally:
            async with self._running_lock:
                self._running = max(0, self._running - 1)

    async def cancel_execution(self, execution_id: str, reason: str = "user") -> bool:
        """
        Cancel flow (D3.4):
          1) читаем trace;
          2) если status != running → no-op;
          3) вызываем backend.cancel(execution_id);
          4) обновляем trace: status=cancelled, cancelled_at, cancel_reason;
          5) пишем в storage + публикуем execution.cancelled.
        """
        trace = await self._load_execution_trace(execution_id)
        if trace is None or trace.status != "running":
            return False

        backend = self._backends.get(trace.backend)
        accepted = False
        if backend is not None and hasattr(backend, "cancel"):
            try:
                accepted = await backend.cancel(execution_id)
            except Exception:
                accepted = False

        now = datetime.now(UTC)
        trace.status = "cancelled"
        trace.finished_at = now
        trace.duration_ms = trace.duration_ms or 0
        trace.cancelled_at = now
        trace.cancel_reason = reason

        await self.on_execution_finish(trace)

        # Отдельное событие execution.cancelled
        event_bus = getattr(self._runtime, "event_bus", None)
        if event_bus is not None and hasattr(event_bus, "publish"):
            try:
                await event_bus.publish(
                    "execution.cancelled",
                    {
                        "execution_id": trace.execution_id,
                        "operation_id": trace.operation_id,
                        "backend": trace.backend,
                        "reason": reason,
                    },
                )
            except Exception:
                pass

        return accepted

    # --- Retry / Replay (D3.5) ---

    def _can_retry(self, trace: ExecutionTrace, policy: Dict[str, Any]) -> tuple[bool, Optional[str], int]:
        """
        Проверяет policy.retry и возвращает (can_retry, error_code, next_retry_index).
        """
        cfg = (policy.get("retry") or {}) if isinstance(policy, dict) else {}
        max_attempts = cfg.get("max_attempts")
        retry_on = cfg.get("retry_on") or ["error", "timeout"]
        allowed_statuses = set(str(s) for s in retry_on)

        if trace.status not in allowed_statuses and trace.status != "cancelled":
            return False, "retry_not_allowed", trace.retry_index

        next_index = trace.retry_index + 1

        if isinstance(max_attempts, int) and max_attempts > 0:
            # attempts считаем как retry_index+1 (текущая попытка) + 1 (новая)
            if next_index + 1 > max_attempts:
                return False, "retry_limit_exceeded", next_index

        return True, None, next_index

    async def retry_execution(self, execution_id: str, reason: str = "retry") -> OperationResult:
        """
        Retry существующего execution:
          - только для статусов error/timeout/cancelled;
          - каждый retry = новый execution_id;
          - новый trace ссылается на previous через parent_execution_id и retry_index.
        """
        policy = await self._load_policy()

        trace = await self._load_execution_trace(execution_id)
        if trace is None:
            return OperationResult(
                ok=False,
                error={"code": "retry_not_allowed", "message": "Execution not found"},
                backend=None,
            )

        if trace.status not in ("error", "timeout", "cancelled"):
            return OperationResult(
                ok=False,
                error={"code": "retry_not_allowed", "message": f"Cannot retry execution in status={trace.status}"},
                backend=trace.backend,
            )

        can, err_code, next_index = self._can_retry(trace, policy)
        if not can:
            return OperationResult(
                ok=False,
                error={"code": err_code or "retry_not_allowed", "message": "Retry is not allowed by policy"},
                backend=trace.backend,
            )

        storage = getattr(self._runtime, "storage", None)
        if storage is None:
            return OperationResult(
                ok=False,
                error={"code": "execution_envelope_not_found", "message": "Storage not available for replay"},
                backend=trace.backend,
            )

        envelope = await storage.get("execution", f"envelopes/{execution_id}")
        if not isinstance(envelope, dict):
            return OperationResult(
                ok=False,
                error={"code": "execution_envelope_not_found", "message": "Cannot replay execution without envelope"},
                backend=trace.backend,
            )

        op_type = str(envelope.get("operation_type") or trace.operation_type)
        params = envelope.get("params") or {}
        base_ctx = envelope.get("context") or {}

        new_execution_id = self._generate_execution_id()
        ctx = dict(base_ctx)
        ctx["_parent_execution_id"] = execution_id
        ctx["_retry_index"] = next_index
        ctx["_execution_id_override"] = new_execution_id

        res = await self.execute_operation(
            operation_id=trace.operation_id,
            operation_type=op_type,
            params=params,
            context=ctx,
        )

        # Событие execution.retried
        try:
            new_trace = await self._load_execution_trace(new_execution_id)
        except Exception:
            new_trace = None

        event_bus = getattr(self._runtime, "event_bus", None)
        if event_bus is not None and hasattr(event_bus, "publish"):
            try:
                await event_bus.publish(
                    "execution.retried",
                    {
                        "parent_execution_id": execution_id,
                        "execution_id": new_execution_id,
                        "retry_index": next_index,
                        "backend": (new_trace.backend if new_trace else trace.backend),
                    },
                )
            except Exception:
                pass

        return res

