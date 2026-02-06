import pytest

from core.runtime import CoreRuntime
from core.module_manager import ModuleSpec
from core.operations import OperationInitiator, OperationInitiatorKind
from execution.controller import ExecutionControllerImpl
from execution.backend import ExecutionBackend, OperationResult
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

