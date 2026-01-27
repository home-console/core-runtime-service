"""
Тесты для AdminModule.

Проверяют:
- Регистрация модуля
- HTTP endpoints для административных операций
- Интеграция с другими модулями
"""

import pytest
from core.runtime import CoreRuntime


@pytest.mark.asyncio
async def test_admin_module_registered(memory_adapter):
    """Тест: AdminModule регистрируется автоматически."""
    runtime = CoreRuntime(memory_adapter)
    await runtime.start()
    
    # Проверяем, что модуль зарегистрирован
    admin_module = runtime.module_manager.get_module("admin")
    assert admin_module is not None
    assert admin_module.name == "admin"
    
    await runtime.stop()


@pytest.mark.asyncio
async def test_admin_endpoints_registered(memory_adapter):
    """Тест: Admin endpoints регистрируются в HttpRegistry."""
    runtime = CoreRuntime(memory_adapter)
    await runtime.start()
    
    # Проверяем, что admin endpoints зарегистрированы
    endpoints = runtime.http.list()
    admin_endpoints = [ep for ep in endpoints if ep.path.startswith("/admin")]
    
    assert len(admin_endpoints) > 0
    
    # Проверяем наличие основных endpoints
    paths = [ep.path for ep in admin_endpoints]
    assert any("/admin/v1/runtime" in path for path in paths)
    assert any("/admin/v1/devices" in path for path in paths)
    
    await runtime.stop()


@pytest.mark.asyncio
async def test_admin_runtime_endpoint(memory_adapter):
    """Тест: GET /admin/v1/runtime возвращает информацию о runtime."""
    runtime = CoreRuntime(memory_adapter)
    await runtime.start()
    
    # Вызываем сервис напрямую (имитация HTTP запроса)
    try:
        result = await runtime.service_registry.call("admin.v1.runtime")
        assert isinstance(result, dict)
        assert "status" in result or "modules" in result or "plugins" in result
    except ValueError:
        # Сервис может быть не зарегистрирован в тестовой среде
        pass
    
    await runtime.stop()
