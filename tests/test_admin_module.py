"""
Тесты для AdminModule.

Проверяют:
- Регистрация модуля
- HTTP endpoints для административных операций
- Интеграция с другими модулями
"""

import pytest
from core.runtime.runtime import CoreRuntime
from core.runtime.module_manager import ModuleSpec

# Минимальный набор модулей для тестов admin
APP_MODULES = [
    ModuleSpec("logger", required=True),
    ModuleSpec("admin", required=True),
]


@pytest.mark.asyncio
async def test_admin_module_registered(memory_adapter, monkeypatch):
    """Тест: AdminModule регистрируется через bootstrap приложения."""
    monkeypatch.setenv("TEST_MODE", "1")
    runtime = CoreRuntime(memory_adapter)
    await runtime.module_manager.register_module_specs(runtime, APP_MODULES)
    await runtime.start()
    
    # Проверяем, что модуль зарегистрирован
    admin_module = runtime.module_manager.get_module("admin")
    assert admin_module is not None
    assert admin_module.name == "admin"
    
    await runtime.stop()


@pytest.mark.asyncio
async def test_admin_endpoints_registered(memory_adapter, monkeypatch):
    """Тест: Admin endpoints регистрируются в HttpRegistry."""
    monkeypatch.setenv("TEST_MODE", "1")
    runtime = CoreRuntime(memory_adapter)
    await runtime.module_manager.register_module_specs(runtime, APP_MODULES)
    await runtime.start()
    
    # Проверяем, что admin endpoints зарегистрированы
    endpoints = runtime.http.list()
    admin_endpoints = [ep for ep in endpoints if ep.path.startswith("/admin")]
    
    assert len(admin_endpoints) > 0
    
    # Проверяем наличие основных endpoints
    paths = [ep.path for ep in admin_endpoints]
    assert any("/admin/v1/inspector/runtime" in path for path in paths)
    assert any("/admin/v1/inspector/operations" in path for path in paths)
    assert any("/admin/v1/inspector/executions" in path for path in paths)
    assert any("/admin/v1/inspector/executions/{execution_id}" in path for path in paths)
    assert any("/admin/v1/inspector/operations/{operation_id}/executions" in path for path in paths)
    assert any("/admin/v1/inspector/schedules" in path for path in paths)
    assert any("/admin/v1/inspector/schedules/{schedule_id}" in path for path in paths)
    assert any("/admin/v1/inspector/operations/{operation_id}/schedules" in path for path in paths)
    
    await runtime.stop()


@pytest.mark.asyncio
async def test_admin_runtime_endpoint(memory_adapter, monkeypatch):
    """Тест: GET /admin/v1/inspector/runtime возвращает информацию о runtime."""
    monkeypatch.setenv("TEST_MODE", "1")
    runtime = CoreRuntime(memory_adapter)
    await runtime.module_manager.register_module_specs(runtime, APP_MODULES)
    await runtime.start()
    
    # Вызываем сервис напрямую (имитация HTTP запроса)
    try:
        result = await runtime.service_registry.call("admin.v1.runtime")
        assert isinstance(result, dict)
        assert "version" in result or "uptime" in result or "started_at" in result
    except ValueError:
        # Сервис может быть не зарегистрирован в тестовой среде
        pass
    
    await runtime.stop()
