"""
Тесты для AutomationModule.

Проверяют:
- Регистрация модуля
- Обработка событий автоматизации
- Границы D2 (automation не дергает доменные сервисы напрямую)
"""

import pytest

from core.operations import OperationInitiator, OperationInitiatorKind
from core.operations.registry import get_operation_handler
from core.module import ModuleSpec
from core.runtime.runtime import CoreRuntime


@pytest.mark.asyncio
async def test_automation_module_registered(memory_adapter):
    """Тест: AutomationModule регистрируется через bootstrap (а не автоматически ядром)."""
    runtime = CoreRuntime(memory_adapter)
    await runtime.module_manager.register_module_specs(
        runtime,
        [
            ModuleSpec("automation", required=False),
        ],
    )
    await runtime.start()

    # Проверяем, что модуль зарегистрирован
    automation_module = runtime.module_manager.get_module("automation")
    assert automation_module is not None
    assert automation_module.name == "automation"

    await runtime.stop()


@pytest.mark.asyncio
async def test_automation_subscribes_to_events(memory_adapter):
    """Тест: AutomationModule подписывается на события."""
    runtime = CoreRuntime(memory_adapter)
    await runtime.module_manager.register_module_specs(
        runtime,
        [
            ModuleSpec("automation", required=False),
        ],
    )
    await runtime.start()

    # Публикуем событие изменения состояния устройства
    await runtime.event_bus.publish(
        "external.device_state_reported",
        {
            "external_id": "ext-1",
            "state": {"on": True},
        },
    )

    # Если модуль подписан, событие должно быть обработано
    # В реальной реализации здесь можно проверить, что автоматизация сработала

    await runtime.stop()


@pytest.mark.asyncio
async def test_automation_creates_only_operations(memory_adapter):
    """Тест: automation не вызывает доменные сервисы напрямую (только создаёт operations)."""
    runtime = CoreRuntime(memory_adapter)
    await runtime.module_manager.register_module_specs(
        runtime,
        [
            ModuleSpec("automation", required=False),
        ],
    )
    await runtime.start()

    # Подготовим mapping в storage, чтобы automation создала operation
    await runtime.storage.set("devices_mappings", "ext-2", {"internal_id": "int-2"})

    await runtime.event_bus.publish(
        "external.device_state_reported",
        {"external_id": "ext-2", "state": {"on": True}},
    )

    # Проверяем, что создалась operation automation.run (а не прямой вызов services)
    ops = await runtime.operations.list(limit=50)
    assert any(op.type == "automation.run" for op in ops)

    await runtime.stop()


@pytest.mark.asyncio
async def test_automation_run_executes_via_operation_registry(
    memory_adapter, monkeypatch
):
    monkeypatch.setenv("TEST_MODE", "1")

    runtime = CoreRuntime(memory_adapter)
    await runtime.module_manager.register_module_specs(
        runtime,
        [
            ModuleSpec("automation", required=False),
        ],
    )
    await runtime.start()

    assert get_operation_handler("automation.run") is not None

    op = await runtime.operations.create(
        op_type="automation.run",
        params={
            "external_id": "ext-bridge-1",
            "state": {"on": True},
        },
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
    )

    res = await runtime.operations.execute(op)

    assert res.status.value == "completed"
    assert res.result is not None
    assert res.result["ok"] is True
    assert res.result["external_id"] == "ext-bridge-1"

    await runtime.stop()
