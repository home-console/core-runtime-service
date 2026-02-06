"""
ExecutionModule (D3) — подключаемый слой исполнения operations.

Ключевая идея:
- НЕ меняем Core (core/), SDK, automation, UI
- Встраиваем execution как RuntimeModule, который приложение может включить/выключить
- Единственная точка интеграции: перехват `runtime.operations.execute()`
  и делегирование в `execution.controller.ExecutionControllerImpl`

Core не знает про process/container/docker — это знания backends, которые живут вне core/.
"""

from __future__ import annotations

import time
import asyncio
from typing import Any, Optional, Callable, Awaitable

from core.runtime_module import RuntimeModule
from core.operations import Operation, OperationStatus, OperationError

from execution.controller import ExecutionControllerImpl
from execution.scheduler import ExecutionScheduler, ExecutionSchedule, generate_schedule_id


class ExecutionModule(RuntimeModule):
    @property
    def name(self) -> str:
        return "execution"

    def __init__(self, runtime: Any):
        super().__init__(runtime)
        self._original_execute: Optional[Callable[[Operation], Awaitable[Operation]]] = None
        self._controller: Optional[ExecutionControllerImpl] = None
        self._scheduler: Optional[ExecutionScheduler] = None
        self._scheduler_task: Optional[asyncio.Task] = None

    async def register(self) -> None:
        # Создаём controller и публикуем в runtime как расширение (не Core API).
        self._controller = ExecutionControllerImpl(self.runtime)
        setattr(self.runtime, "execution_controller", self._controller)

        ops_mgr = getattr(self.runtime, "operations", None)
        if ops_mgr is None:
            return

        # Operation: execution.cancel (D3.4)
        async def _handle_execution_cancel(params: dict, context: dict) -> dict:
            execution_id = params.get("execution_id")
            if not execution_id:
                return {"status": "error", "error": {"code": "missing_execution_id", "message": "execution_id is required"}}

            controller: ExecutionControllerImpl = getattr(self.runtime, "execution_controller", None)
            if controller is None:
                return {"status": "error", "error": {"code": "no_execution_controller", "message": "Execution controller not available"}}

            accepted = await controller.cancel_execution(execution_id=str(execution_id), reason="user")
            return {
                "status": "cancelled" if accepted else "noop",
                "execution_id": str(execution_id),
            }

        ops_mgr.register_handler("execution.cancel", _handle_execution_cancel)

        # Operation: execution.retry (D3.5)
        async def _handle_execution_retry(params: dict, context: dict) -> dict:
            execution_id = params.get("execution_id")
            if not execution_id:
                return {
                    "status": "error",
                    "error": {"code": "missing_execution_id", "message": "execution_id is required"},
                }

            controller: ExecutionControllerImpl = getattr(self.runtime, "execution_controller", None)
            if controller is None:
                return {
                    "status": "error",
                    "error": {"code": "no_execution_controller", "message": "Execution controller not available"},
                }

            res = await controller.retry_execution(str(execution_id))
            return {
                "ok": res.ok,
                "error": res.error,
                "backend": res.backend,
            }

        ops_mgr.register_handler("execution.retry", _handle_execution_retry)

        # Operations: execution.schedule.* (D3.6)

        async def _handle_schedule_create(params: dict, context: dict) -> dict:
            operation_type = params.get("operation_type")
            trigger = params.get("trigger") or {}
            if not isinstance(operation_type, str) or not operation_type:
                return {
                    "status": "error",
                    "error": {"code": "invalid_operation_type", "message": "operation_type is required"},
                }

            trigger_type = (trigger.get("type") or "interval").lower()
            if trigger_type not in ("delay", "interval", "cron"):
                return {
                    "status": "error",
                    "error": {"code": "unsupported_trigger_type", "message": f"Unsupported trigger type: {trigger_type}"},
                }

            from datetime import datetime, UTC, timedelta

            now = datetime.now(UTC)
            every_seconds = trigger.get("every_seconds")
            at_raw = trigger.get("at")

            from execution.scheduler import _parse_datetime_optional, compute_next_run  # type: ignore[attr-defined]

            trigger_at = None
            if at_raw is not None:
                trigger_at = _parse_datetime_optional(at_raw)

            cron_expr = None
            cron_tz = "UTC"

            if trigger_type == "cron":
                # Для cron запрещаем at/every_seconds.
                if every_seconds is not None or at_raw is not None:
                    return {
                        "status": "error",
                        "error": {
                            "code": "invalid_cron_trigger",
                            "message": "at/every_seconds must not be set for cron trigger",
                        },
                    }
                cron_expr = trigger.get("expr") or trigger.get("cron")
                if not isinstance(cron_expr, str) or not cron_expr.strip():
                    return {
                        "status": "error",
                        "error": {"code": "invalid_cron_expr", "message": "cron expr is required for cron trigger"},
                    }
                cron_tz = trigger.get("timezone") or "UTC"
                # Проверяем cron expr/таймзону через compute_next_run (pure).
                try:
                    _ = compute_next_run(
                        cron_expr=cron_expr,
                        timezone=cron_tz,
                        last_run_at=None,
                        now=now,
                    )
                except Exception as e:
                    return {
                        "status": "error",
                        "error": {"code": "invalid_cron_expr", "message": str(e)},
                    }
                # next_run_at будет вычислен ExecutionSchedule.ensure_next_run_at
                next_run_at = None
            elif trigger_type == "delay":
                # Один запуск в момент at (или сразу, если не задан).
                next_run_at = trigger_at or now
            else:
                # interval
                try:
                    sec = int(every_seconds) if every_seconds is not None else 0
                except (TypeError, ValueError):
                    sec = 0
                if sec <= 0:
                    return {
                        "status": "error",
                        "error": {
                            "code": "invalid_interval",
                            "message": "every_seconds must be positive for interval trigger",
                        },
                    }
                next_run_at = now + timedelta(seconds=sec)

            schedule_id = generate_schedule_id()
            from execution.scheduler import ExecutionSchedule

            sched = ExecutionSchedule(
                schedule_id=schedule_id,
                operation_type=operation_type,
                params=params.get("params") or {},
                context=params.get("context") or {},
                trigger_type=trigger_type,  # type: ignore[arg-type]
                trigger_at=trigger_at,
                trigger_every_seconds=int(every_seconds) if every_seconds is not None else None,
                trigger_cron=cron_expr,
                cron_expr=cron_expr,
                cron_timezone=cron_tz,
                enabled=True,
                max_runs=params.get("max_runs"),
                run_count=0,
                last_run_at=None,
                next_run_at=next_run_at,
            )

            scheduler = ExecutionScheduler(self.runtime, self._controller)
            await scheduler.save_schedule(sched)

            # Событие creation (best-effort)
            event_bus = getattr(self.runtime, "event_bus", None)
            if event_bus is not None and hasattr(event_bus, "publish"):
                try:
                    await event_bus.publish(
                        "execution.scheduled",
                        {
                            "schedule_id": schedule_id,
                            "operation_type": operation_type,
                        },
                    )
                except Exception:
                    pass

            return {"status": "ok", "schedule_id": schedule_id}

        async def _load_schedule(schedule_id: str) -> Optional[ExecutionSchedule]:
            storage = getattr(self.runtime, "storage", None)
            if storage is None:
                return None
            try:
                data = await storage.get("execution", f"schedules/{schedule_id}")
            except Exception:
                return None
            if not isinstance(data, dict):
                return None
            return ExecutionSchedule.from_dict(data)

        async def _persist_schedule(sched: ExecutionSchedule) -> None:
            scheduler = ExecutionScheduler(self.runtime, self._controller)
            await scheduler.save_schedule(sched)

        async def _handle_schedule_pause(params: dict, context: dict) -> dict:
            schedule_id = params.get("schedule_id")
            if not schedule_id:
                return {
                    "status": "error",
                    "error": {"code": "missing_schedule_id", "message": "schedule_id is required"},
                }
            sched = await _load_schedule(str(schedule_id))
            if not sched:
                return {
                    "status": "error",
                    "error": {"code": "schedule_not_found", "message": "Schedule not found"},
                }
            sched.enabled = False
            await _persist_schedule(sched)

            event_bus = getattr(self.runtime, "event_bus", None)
            if event_bus is not None and hasattr(event_bus, "publish"):
                try:
                    await event_bus.publish(
                        "execution.schedule.disabled",
                        {
                            "schedule_id": sched.schedule_id,
                            "operation_type": sched.operation_type,
                            "reason": "manual_pause",
                        },
                    )
                except Exception:
                    pass

            return {"status": "ok", "schedule_id": sched.schedule_id}

        async def _handle_schedule_resume(params: dict, context: dict) -> dict:
            from datetime import datetime, UTC, timedelta

            schedule_id = params.get("schedule_id")
            if not schedule_id:
                return {
                    "status": "error",
                    "error": {"code": "missing_schedule_id", "message": "schedule_id is required"},
                }
            sched = await _load_schedule(str(schedule_id))
            if not sched:
                return {
                    "status": "error",
                    "error": {"code": "schedule_not_found", "message": "Schedule not found"},
                }
            now = datetime.now(UTC)
            sched.enabled = True
            # При resume пересчитываем next_run_at от текущего момента.
            if sched.trigger_type == "interval":
                sec = sched.trigger_every_seconds or 0
                if sec <= 0:
                    sched.enabled = False
                    sched.next_run_at = None
                else:
                    sched.next_run_at = now + timedelta(seconds=sec)
            elif sched.trigger_type == "delay":
                # Если ещё ни разу не запускали — запускаем как delay от сейчас.
                if sched.run_count == 0:
                    sched.next_run_at = now
                else:
                    # Уже был запуск delay — дальнейшее resume не имеет смысла.
                    sched.enabled = False
                    sched.next_run_at = None
            else:
                sched.enabled = False
                sched.next_run_at = None

            await _persist_schedule(sched)
            return {"status": "ok", "schedule_id": sched.schedule_id}

        async def _handle_schedule_delete(params: dict, context: dict) -> dict:
            schedule_id = params.get("schedule_id")
            if not schedule_id:
                return {
                    "status": "error",
                    "error": {"code": "missing_schedule_id", "message": "schedule_id is required"},
                }
            storage = getattr(self.runtime, "storage", None)
            if storage is None:
                return {
                    "status": "error",
                    "error": {"code": "storage_unavailable", "message": "Storage not available"},
                }
            sid = str(schedule_id)
            # Удаляем сам schedule
            try:
                await storage.delete("execution", f"schedules/{sid}")
            except Exception:
                pass
            # Чистим индексы по operation_type
            try:
                keys = await storage.list_keys("execution")
            except Exception:
                keys = []
            for key in keys:
                if key.startswith("schedules_by_operation/") and key.endswith(f"/{sid}"):
                    try:
                        await storage.delete("execution", key)
                    except Exception:
                        continue
            return {"status": "ok", "schedule_id": sid}

        ops_mgr.register_handler("execution.schedule.create", _handle_schedule_create)
        ops_mgr.register_handler("execution.schedule.pause", _handle_schedule_pause)
        ops_mgr.register_handler("execution.schedule.resume", _handle_schedule_resume)
        ops_mgr.register_handler("execution.schedule.delete", _handle_schedule_delete)

        if self._original_execute is None:
            self._original_execute = ops_mgr.execute

        async def _execute_with_execution(operation: Operation) -> Operation:
            """
            Обёртка вокруг OperationManager.execute:
            validate → mark running → delegate to execution_controller → persist.

            Важно: `InProcessBackend` НЕ вызывает ops_mgr.execute(), а обращается
            напрямую к handlers, чтобы избежать рекурсии.
            """
            try:
                # 1) Validate (как в core.operations.OperationManager.execute)
                handlers = getattr(ops_mgr, "_handlers", {})
                if operation.type not in handlers:
                    operation.status = OperationStatus.FAILED
                    operation.error = OperationError(
                        code="unknown_operation_type",
                        message=f"No handler for operation type: {operation.type}",
                    )
                    await ops_mgr._persist(operation)  # type: ignore[attr-defined]
                    return operation

                # 2) Mark as running
                operation.status = OperationStatus.RUNNING
                operation.started_at = time.time()
                await ops_mgr._persist(operation)  # type: ignore[attr-defined]

                # 3) Delegate to execution controller (policy + backend)
                controller = getattr(self.runtime, "execution_controller", None)
                if controller is None:
                    # fallback: original behavior (should not happen if module registered)
                    return await self._original_execute(operation)  # type: ignore[misc]

                op_res = await controller.execute_operation(
                    operation_id=operation.operation_id,
                    operation_type=operation.type,
                    params=operation.params,
                    context={"runtime": self.runtime, "operation_id": operation.operation_id},
                )

                if op_res.ok:
                    operation.status = OperationStatus.SUCCESS
                    operation.result = op_res.result or {}
                else:
                    operation.status = OperationStatus.FAILED
                    err = op_res.error or {"code": "execution_error", "message": "Unknown execution error"}
                    operation.error = OperationError(code=str(err.get("code", "execution_error")), message=str(err.get("message", "")), details=err)

                operation.finished_at = time.time()
            except Exception as e:
                operation.status = OperationStatus.FAILED
                operation.error = OperationError(code="execution_error", message=str(e))
                operation.finished_at = time.time()

            await ops_mgr._persist(operation)  # type: ignore[attr-defined]
            return operation

        # Monkeypatch: operations subsystem делегирует сюда, не зная policy/backend.
        ops_mgr.execute = _execute_with_execution  # type: ignore[assignment]

    async def start(self) -> None:
        # Запускаем фоновый scheduler (D3.6).
        if self._controller is None:
            self._controller = ExecutionControllerImpl(self.runtime)
            setattr(self.runtime, "execution_controller", self._controller)

        self._scheduler = ExecutionScheduler(self.runtime, self._controller)

        async def _run_scheduler() -> None:
            try:
                while True:
                    await self._scheduler.tick()
                    # Простой sleep, без tight-loop и cron в core.
                    await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                return

        self._scheduler_task = asyncio.create_task(_run_scheduler())

    async def stop(self) -> None:
        # Останавливаем scheduler task, если он был запущен.
        if self._scheduler_task is not None:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
            self._scheduler_task = None

        # Восстанавливаем оригинальный execute, если он был перехвачен.
        ops_mgr = getattr(self.runtime, "operations", None)
        if ops_mgr is not None and self._original_execute is not None:
            ops_mgr.execute = self._original_execute  # type: ignore[assignment]

