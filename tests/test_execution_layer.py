import pytest

from core.runtime import CoreRuntime
from core.module_manager import ModuleSpec
from core.operations import OperationInitiator, OperationInitiatorKind


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

    # ProcessBackend пока заглушка => ожидаем failed с not_implemented,
    # но важное: routing произошёл без изменений Core/SDK/plugin/automation.
    assert res.status.value == "failed"
    assert res.error is not None
    assert res.error.code == "not_implemented"

    await runtime.stop()

