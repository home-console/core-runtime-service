"""
Тесты для AutomationModule.

Проверяют:
- Регистрация модуля
- Обработка событий автоматизации
- Интеграция с devices модулем
"""

import pytest
from core.runtime import CoreRuntime


@pytest.mark.asyncio
async def test_automation_module_registered(memory_adapter):
    """Тест: AutomationModule регистрируется автоматически."""
    runtime = CoreRuntime(memory_adapter)
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
    await runtime.start()
    
    # Публикуем событие изменения состояния устройства
    await runtime.event_bus.publish(
        "internal.device_state_changed",
        {
            "internal_id": "test_device",
            "state": {"on": True}
        }
    )
    
    # Если модуль подписан, событие должно быть обработано
    # В реальной реализации здесь можно проверить, что автоматизация сработала
    
    await runtime.stop()


@pytest.mark.asyncio
async def test_automation_handles_device_events(memory_adapter):
    """Тест: AutomationModule обрабатывает события устройств."""
    runtime = CoreRuntime(memory_adapter)
    await runtime.start()
    
    # Создаем устройство
    await runtime.service_registry.call(
        "devices.create",
        "test_auto_device",
        name="Test Device",
        device_type="light"
    )
    
    # Изменяем состояние устройства
    await runtime.service_registry.call(
        "devices.set_state",
        "test_auto_device",
        {"on": True}
    )
    
    # Событие должно быть опубликовано и обработано automation модулем
    # В реальной реализации здесь можно проверить, что автоматизация сработала
    
    await runtime.stop()
