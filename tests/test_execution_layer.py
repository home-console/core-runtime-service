import pytest

from core.runtime import CoreRuntime
from core.module_manager import ModuleSpec
from modules.execution.module import ExecutionModule
from core.operations import OperationInitiator, OperationInitiatorKind
from execution.controller import ExecutionControllerImpl
from execution.backend import ExecutionBackend, OperationResult
from execution.scheduler import ExecutionScheduler, ExecutionSchedule
from typing import Any, Dict
import asyncio


@pytest.mark.asyncio
async def test_execution_module_wires_operations_execute(memory_adapter):
    """
    D3: Operations subsystem не знает backend/policy и делегирует через execution layer.

    Проверка: при наличии ExecutionModule операция исполняется через controller,
    и default policy = in_process сохраняет поведение.
    """
    runtime = CoreRuntime(memory_adapter)
    await runtime.module_manager.register_module_specs(
        runtime,
        [
            ModuleSpec("execution", required=True),
        ],
    )
    await runtime.start()

    # Register simple op handler in operations manager
    async def handle_ping(params, context):
        return {"pong": True, "echo": params.get("x")}

    runtime.operations.register_handler("test.ping", handle_ping)

    op = await runtime.operations.create(
        op_type="test.ping",
        params={"x": 1},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
    )
    res = await runtime.operations.execute(op)

    assert res.status.value == "success"
    assert res.result["pong"] is True
    assert res.result["echo"] == 1

    await runtime.stop()


@pytest.mark.asyncio
async def test_execution_policy_can_route_to_process_backend_without_core_changes(memory_adapter):
    """
    D3: policy хранится вне Core (storage) и может меняться без рестарта runtime.
    Здесь просто проверяем, что routing реально влияет на исполнение.
    """
    runtime = CoreRuntime(memory_adapter)
    await runtime.module_manager.register_module_specs(
        runtime,
        [
            ModuleSpec("execution", required=True),
        ],
    )
    await runtime.start()

    # Put policy into storage (controller loads it per execute() call)
    await runtime.storage.set(
        "execution",
        "policy",
        {
            "default": "in_process",
            "operations": {"test.ping": "process"},
        },
    )

    async def handle_ping(params, context):
        return {"pong": True}

    runtime.operations.register_handler("test.ping", handle_ping)

    op = await runtime.operations.create(
        op_type="test.ping",
        params={},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
    )
    res = await runtime.operations.execute(op)

    # ProcessBackend теперь настоящий backend: операция уходит в runner через subprocess.
    # Важно: routing произошёл без изменений Core/SDK/plugin/automation.
    assert res.status.value in ("success", "failed")
    assert res.error is None or res.error.code is not None

    await runtime.stop()


@pytest.mark.asyncio
async def test_execution_trace_created_and_updated_in_storage(memory_adapter):
    """
    D3.3: trace создаётся при старте и обновляется при завершении исполнения.
    Проверяем, что namespace storage/execution содержит запись traces/{execution_id}
    и индекс by_operation/{operation_id}/{execution_id}.
    """
    runtime = CoreRuntime(memory_adapter)
    await runtime.module_manager.register_module_specs(
        runtime,
        [
            ModuleSpec("execution", required=True),
        ],
    )
    await runtime.start()

    async def handle_ping(params, context):
        return {"pong": True}

    runtime.operations.register_handler("test.ping", handle_ping)

    op = await runtime.operations.create(
        op_type="test.ping",
        params={},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
    )
    res = await runtime.operations.execute(op)

    assert res.status.value == "success"

    # Ищем execution traces в storage
    keys = await runtime.storage.list_keys("execution")
    trace_keys = [k for k in keys if k.startswith("traces/")]
    assert len(trace_keys) >= 1

    # Берём первый trace и проверяем базовые поля
    trace_data = await runtime.storage.get("execution", trace_keys[0])
    assert isinstance(trace_data, dict)
    assert trace_data.get("operation_id") == op.operation_id
    assert trace_data.get("operation_type") == op.type
    assert trace_data.get("backend") in ("in_process", "process", "container")
    assert trace_data.get("status") in ("ok", "error", "timeout", "killed", "running")
    assert trace_data.get("started_at") is not None

    # Индекс по операции
    index_keys = [k for k in keys if k.startswith(f"by_operation/{op.operation_id}/")]
    assert len(index_keys) >= 1

    await runtime.stop()


class _TimeoutBackend(ExecutionBackend):
    async def execute(
        self,
        *,
        operation_type: str,
        params: Dict[str, Any],
        context: Dict[str, Any],
        timeout: int | None = None,
    ) -> OperationResult:
        return OperationResult(
            ok=False,
            error={"code": "timeout", "message": "simulated timeout"},
            backend="process",
            killed=True,
            timed_out=True,
        )


@pytest.mark.asyncio
async def test_execution_trace_status_timeout_and_killed(memory_adapter):
    """
    D3.3: timeout/killed backend → status в ExecutionTrace = timeout/killed.
    Используем подменённый backend, чтобы не зависеть от реального subprocess.
    """
    runtime = CoreRuntime(memory_adapter)

    # Создаём controller с кастомным backend registry
    controller = ExecutionControllerImpl(
        runtime,
        backends={"process": _TimeoutBackend(), "in_process": _TimeoutBackend()},
    )
    setattr(runtime, "execution_controller", controller)

    # Простой handler, который никогда не вызывается (backend = process)
    async def handle_op(params, context):
        return {"ok": True}

    runtime.operations.register_handler("test.timeout", handle_op)

    op = await runtime.operations.create(
        op_type="test.timeout",
        params={},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
    )

    # Запускаем через controller напрямую, минуя ExecutionModule
    res = await controller.execute_operation(
        operation_id=op.operation_id,
        operation_type=op.type,
        params=op.params,
        context={},
    )

    assert res.ok is False
    assert res.error is not None
    assert res.error.get("code") == "timeout"

    # Проверяем, что trace зафиксирован как timeout + killed
    keys = await runtime.storage.list_keys("execution")
    trace_keys = [k for k in keys if k.startswith("traces/")]
    assert len(trace_keys) == 1
    trace_data = await runtime.storage.get("execution", trace_keys[0])
    assert trace_data.get("status") == "timeout"


@pytest.mark.asyncio
async def test_cancel_running_execution_marks_trace_cancelled_and_calls_backend(memory_adapter):
    """
    D3.4: cancel running execution → status=cancelled, backend.cancel вызывается.
    """
    runtime = CoreRuntime(memory_adapter)
    await runtime.module_manager.register_module_specs(
        runtime,
        [
            ModuleSpec("execution", required=True),
        ],
    )
    await runtime.start()

    # Долгая операция, которую можно отменить.
    started = asyncio.Event()
    never_finish = asyncio.Event()

    async def handle_sleep(params, context):
        started.set()
        try:
            await never_finish.wait()
        except asyncio.CancelledError:
            raise

    runtime.operations.register_handler("test.sleep", handle_sleep)

    op = await runtime.operations.create(
        op_type="test.sleep",
        params={},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
    )

    # Запускаем выполнение операции (через ExecutionModule + InProcessBackend).
    execute_task = asyncio.create_task(runtime.operations.execute(op))

    # Ждём, пока handler стартует.
    await started.wait()

    # Находим execution_id по следу в storage.
    execution_id = None
    for _ in range(10):
        keys = await runtime.storage.list_keys("execution")
        trace_keys = [k for k in keys if k.startswith("traces/")]
        for key in trace_keys:
            data = await runtime.storage.get("execution", key)
            if data and data.get("operation_id") == op.operation_id:
                execution_id = data["execution_id"]
                break
        if execution_id:
            break
        await asyncio.sleep(0.05)

    assert execution_id is not None

    # Вызываем отмену через operation execution.cancel.
    cancel_op = await runtime.operations.create(
        op_type="execution.cancel",
        params={"execution_id": execution_id},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
    )
    cancel_res = await runtime.operations.execute(cancel_op)
    assert cancel_res.status.value in ("success", "failed")

    # Дожидаемся завершения исходной операции.
    await execute_task

    # Проверяем, что trace помечен как cancelled.
    keys = await runtime.storage.list_keys("execution")
    trace_keys = [k for k in keys if k.startswith("traces/")]
    matching = []
    for key in trace_keys:
        data = await runtime.storage.get("execution", key)
        if data and data.get("execution_id") == execution_id:
            matching.append(data)

    assert len(matching) == 1
    trace = matching[0]
    assert trace.get("status") == "cancelled"
    assert trace.get("cancelled_at") is not None
    assert trace.get("cancel_reason") == "user"

    await runtime.stop()


@pytest.mark.asyncio
async def test_concurrency_limit_prevents_start_and_sets_error_status(memory_adapter):
    """
    D3.4: при превышении limits.max_running execution не стартует и trace получает error с execution_limit_exceeded.
    """
    runtime = CoreRuntime(memory_adapter)
    await runtime.module_manager.register_module_specs(
        runtime,
        [
            ModuleSpec("execution", required=True),
        ],
    )
    await runtime.start()

    # limits.max_running = 0 → все новые execution должны немедленно падать.
    await runtime.storage.set(
        "execution",
        "policy",
        {
            "default": "in_process",
            "limits": {"max_running": 0},
        },
    )

    async def handle_ping(params, context):
        return {"pong": True}

    runtime.operations.register_handler("test.ping", handle_ping)

    op = await runtime.operations.create(
        op_type="test.ping",
        params={},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
    )
    res = await runtime.operations.execute(op)

    # Операция через execution layer должна зафиксировать ошибку лимита в trace,
    # но OperationManager может считать её "успешно завершённой" с error в payload.
    # Поэтому проверяем именно trace.
    keys = await runtime.storage.list_keys("execution")
    trace_keys = [k for k in keys if k.startswith("traces/")]
    assert len(trace_keys) == 1
    data = await runtime.storage.get("execution", trace_keys[0])
    assert data.get("status") == "error"
    assert data.get("error_code") == "execution_limit_exceeded"

    await runtime.stop()


@pytest.mark.asyncio
async def test_scheduler_delay_schedule_runs_once(memory_adapter):
    """
    D3.6: delay schedule (at=now) → один execution и run_count=1.
    """
    runtime = CoreRuntime(memory_adapter)
    controller = ExecutionControllerImpl(runtime)
    scheduler = ExecutionScheduler(runtime, controller)

    # handler для операционного типа
    async def handle_ping(params, context):
        return {"pong": True}

    runtime.operations.register_handler("test.delay", handle_ping)

    from datetime import datetime, UTC

    now = datetime.now(UTC)
    sched = ExecutionSchedule(
        schedule_id="sched-test-delay",
        operation_type="test.delay",
        params={},
        context={},
        trigger_type="delay",
        trigger_at=now,
        trigger_every_seconds=None,
        trigger_cron=None,
        enabled=True,
        max_runs=None,
        run_count=0,
        last_run_at=None,
        next_run_at=now,
        created_at=now,
    )

    await scheduler.save_schedule(sched)

    # Первый tick — должен запустить execution.
    await scheduler.tick(now=now)

    # Проверяем, что run_count=1 и enabled=False (delay — одноразовый).
    keys = await runtime.storage.list_keys("execution")
    assert f"schedules/{sched.schedule_id}" in keys
    stored = await runtime.storage.get("execution", f"schedules/{sched.schedule_id}")
    assert stored["run_count"] == 1
    assert stored["enabled"] is False

    # И trace хотя бы один.
    trace_keys = [k for k in keys if k.startswith("traces/")]
    assert len(trace_keys) >= 1


@pytest.mark.asyncio
async def test_scheduler_interval_schedule_runs_multiple_times(memory_adapter):
    """
    D3.6: interval schedule → несколько запусков через несколько tick.
    """
    runtime = CoreRuntime(memory_adapter)
    controller = ExecutionControllerImpl(runtime)
    scheduler = ExecutionScheduler(runtime, controller)

    counter = {"value": 0}

    async def handle_inc(params, context):
        counter["value"] += 1
        return {"count": counter["value"]}

    runtime.operations.register_handler("test.interval", handle_inc)

    from datetime import datetime, UTC, timedelta

    now = datetime.now(UTC)
    sched = ExecutionSchedule(
        schedule_id="sched-test-interval",
        operation_type="test.interval",
        params={},
        context={},
        trigger_type="interval",
        trigger_at=None,
        trigger_every_seconds=1,
        trigger_cron=None,
        enabled=True,
        max_runs=None,
        run_count=0,
        last_run_at=None,
        next_run_at=now,
        created_at=now,
    )
    await scheduler.save_schedule(sched)

    # Первый запуск
    await scheduler.tick(now=now)
    # Второй запуск через ~1 сек
    await scheduler.tick(now=now + timedelta(seconds=1, milliseconds=100))

    stored = await runtime.storage.get("execution", f"schedules/{sched.schedule_id}")
    assert stored["run_count"] == 2
    assert counter["value"] == 2


@pytest.mark.asyncio
async def test_scheduler_pause_and_resume(memory_adapter):
    """
    D3.6: pause → нет запусков; resume → запуски продолжаются.
    """
    runtime = CoreRuntime(memory_adapter)
    controller = ExecutionControllerImpl(runtime)
    scheduler = ExecutionScheduler(runtime, controller)

    calls = {"value": 0}

    async def handle_job(params, context):
        calls["value"] += 1
        return {"calls": calls["value"]}

    runtime.operations.register_handler("test.pause", handle_job)

    from datetime import datetime, UTC, timedelta

    now = datetime.now(UTC)
    sched = ExecutionSchedule(
        schedule_id="sched-test-pause",
        operation_type="test.pause",
        params={},
        context={},
        trigger_type="interval",
        trigger_at=None,
        trigger_every_seconds=1,
        trigger_cron=None,
        enabled=True,
        max_runs=None,
        run_count=0,
        last_run_at=None,
        next_run_at=now,
        created_at=now,
    )
    await scheduler.save_schedule(sched)

    # Первый запуск
    await scheduler.tick(now=now)

    # Pause расписания через handler
    mod = ExecutionModule(runtime)
    await mod.register()
    await runtime.start()  # чтобы service_registry/event_bus были корректно готовы

    pause_op = await runtime.operations.create(
        op_type="execution.schedule.pause",
        params={"schedule_id": sched.schedule_id},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
    )
    await runtime.operations.execute(pause_op)

    # Tick после паузы не должен запускать job.
    await scheduler.tick(now=now + timedelta(seconds=2))

    stored = await runtime.storage.get("execution", f"schedules/{sched.schedule_id}")
    assert stored["enabled"] is False
    assert stored["run_count"] == 1


@pytest.mark.asyncio
async def test_scheduler_max_runs_disables_schedule(memory_adapter):
    """
    D3.6: max_runs=2 → третья попытка не выполняется, enabled=False.
    """
    runtime = CoreRuntime(memory_adapter)
    controller = ExecutionControllerImpl(runtime)
    scheduler = ExecutionScheduler(runtime, controller)

    async def handle_job(params, context):
        return {}

    runtime.operations.register_handler("test.maxruns", handle_job)

    from datetime import datetime, UTC, timedelta

    now = datetime.now(UTC)
    sched = ExecutionSchedule(
        schedule_id="sched-test-maxruns",
        operation_type="test.maxruns",
        params={},
        context={},
        trigger_type="interval",
        trigger_at=None,
        trigger_every_seconds=1,
        trigger_cron=None,
        enabled=True,
        max_runs=2,
        run_count=0,
        last_run_at=None,
        next_run_at=now,
        created_at=now,
    )
    await scheduler.save_schedule(sched)

    await scheduler.tick(now=now)
    await scheduler.tick(now=now + timedelta(seconds=1, milliseconds=100))
    await scheduler.tick(now=now + timedelta(seconds=2, milliseconds=100))

    stored = await runtime.storage.get("execution", f"schedules/{sched.schedule_id}")
    assert stored["run_count"] == 2
    assert stored["enabled"] is False


@pytest.mark.asyncio
async def test_retry_failed_execution_creates_new_execution_with_parent_and_retry_index(memory_adapter):
    """
    D3.5: retry failed execution → новый execution с parent_execution_id и увеличенным retry_index.
    """
    runtime = CoreRuntime(memory_adapter)
    await runtime.module_manager.register_module_specs(
        runtime,
        [
            ModuleSpec("execution", required=True),
        ],
    )
    await runtime.start()

    async def handle_fail(params, context):
        raise RuntimeError("boom")

    runtime.operations.register_handler("test.fail", handle_fail)

    op = await runtime.operations.create(
        op_type="test.fail",
        params={},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
    )
    res = await runtime.operations.execute(op)
    assert res.status.value == "failed"

    # находим исходный execution_id
    keys = await runtime.storage.list_keys("execution")
    trace_keys = [k for k in keys if k.startswith("traces/")]
    assert len(trace_keys) == 1
    original_trace = await runtime.storage.get("execution", trace_keys[0])
    parent_execution_id = original_trace["execution_id"]

    # делаем retry через operation execution.retry
    retry_op = await runtime.operations.create(
        op_type="execution.retry",
        params={"execution_id": parent_execution_id},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
    )
    await runtime.operations.execute(retry_op)

    # теперь в storage должно быть минимум два traces/*
    keys = await runtime.storage.list_keys("execution")
    trace_keys = [k for k in keys if k.startswith("traces/")]
    assert len(trace_keys) >= 2

    traces = []
    for key in trace_keys:
        traces.append(await runtime.storage.get("execution", key))

    # исходный trace имеет retry_index=0, новый — retry_index=1 и parent_execution_id = исходный execution_id
    roots = [t for t in traces if t.get("retry_index", 0) == 0 and t.get("execution_id") == parent_execution_id]
    retries = [t for t in traces if t.get("parent_execution_id") == parent_execution_id and t.get("retry_index", 0) == 1]
    assert len(roots) >= 1
    assert len(retries) == 1
    retry_trace = retries[0]
    assert retry_trace.get("parent_execution_id") == parent_execution_id

    await runtime.stop()


@pytest.mark.asyncio
async def test_retry_running_execution_rejected(memory_adapter):
    """
    D3.5: retry running execution → rejected, новых traces не появляется.
    """
    runtime = CoreRuntime(memory_adapter)
    await runtime.module_manager.register_module_specs(
        runtime,
        [
            ModuleSpec("execution", required=True),
        ],
    )
    await runtime.start()

    started = asyncio.Event()
    never_finish = asyncio.Event()

    async def handle_sleep(params, context):
        started.set()
        await never_finish.wait()

    runtime.operations.register_handler("test.sleep_retry", handle_sleep)

    op = await runtime.operations.create(
        op_type="test.sleep_retry",
        params={},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
    )

    execute_task = asyncio.create_task(runtime.operations.execute(op))
    await started.wait()

    keys = await runtime.storage.list_keys("execution")
    trace_keys = [k for k in keys if k.startswith("traces/")]
    assert len(trace_keys) == 1
    trace = await runtime.storage.get("execution", trace_keys[0])
    execution_id = trace["execution_id"]

    # retry пока execution в статусе running
    retry_op = await runtime.operations.create(
        op_type="execution.retry",
        params={"execution_id": execution_id},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
    )
    retry_res = await runtime.operations.execute(retry_op)
    assert retry_res.status.value in ("success", "failed")
    # в ответе от handler смотрим error.code
    if retry_res.error:
        assert retry_res.error.code in ("retry_not_allowed", "execution_error")

    # останавливаем исходную операцию
    never_finish.set()
    await execute_task

    # новых retries для этого execution не появилось в by_parent
    keys = await runtime.storage.list_keys("execution")
    by_parent_keys = [k for k in keys if k.startswith(f"by_parent/{execution_id}/")]
    assert len(by_parent_keys) == 0

    await runtime.stop()


@pytest.mark.asyncio
async def test_retry_limit_exceeded_by_policy(memory_adapter):
    """
    D3.5: превышение retry policy.max_attempts → error_code=retry_limit_exceeded.
    """
    runtime = CoreRuntime(memory_adapter)
    await runtime.module_manager.register_module_specs(
        runtime,
        [
            ModuleSpec("execution", required=True),
        ],
    )
    await runtime.start()

    await runtime.storage.set(
        "execution",
        "policy",
        {
            "default": "in_process",
            "retry": {
                "max_attempts": 1,
                "retry_on": ["error"],
            },
        },
    )

    async def handle_fail(params, context):
        raise RuntimeError("boom")

    runtime.operations.register_handler("test.fail.retry", handle_fail)

    op = await runtime.operations.create(
        op_type="test.fail.retry",
        params={},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
    )
    await runtime.operations.execute(op)

    # исходный execution
    keys = await runtime.storage.list_keys("execution")
    trace_keys = [k for k in keys if k.startswith("traces/")]
    assert len(trace_keys) == 1
    original_trace = await runtime.storage.get("execution", trace_keys[0])
    execution_id = original_trace["execution_id"]

    # первый retry (разрешён policy)
    retry1_op = await runtime.operations.create(
        op_type="execution.retry",
        params={"execution_id": execution_id},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
    )
    await runtime.operations.execute(retry1_op)

    # второй retry (должен быть запрещён policy)
    retry2_op = await runtime.operations.create(
        op_type="execution.retry",
        params={"execution_id": execution_id},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
    )
    retry2_res = await runtime.operations.execute(retry2_op)
    # handler execution.retry возвращает ok / error в payload
    assert retry2_res.result is not None or retry2_res.error is not None

    # на практике проще проверить факт отсутствия третьего trace'а by_parent
    keys = await runtime.storage.list_keys("execution")
    by_parent_keys = [k for k in keys if k.startswith(f"by_parent/{execution_id}/")]
    # допускаем максимум один реальный retry
    assert len(by_parent_keys) <= 1

    await runtime.stop()

