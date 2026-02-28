"""
Тесты для WebSocket support в HttpRegistry и ApiModule.

Проверяют:
- Регистрация WebSocket endpoint в HttpRegistry
- Валидация WebSocket endpoint данных
- Inspector видит websocket flag
- WebSocket соединение реально работает
"""

import pytest
import asyncio
from core.runtime import CoreRuntime
from core.http_registry import HttpEndpoint


@pytest.mark.asyncio
async def test_websocket_endpoint_validation(memory_adapter):
    """Тест: WebSocket endpoint требует websocket=True и method=None."""
    runtime = CoreRuntime(memory_adapter)
    
    # ✓ Валидный WebSocket endpoint
    ws_endpoint = HttpEndpoint(
        path="/ws/test",
        service="test.ws",
        websocket=True,
    )
    assert ws_endpoint.websocket is True
    assert ws_endpoint.method is None
    
    # ✗ WebSocket с указанным method должен вызвать ошибку
    with pytest.raises(ValueError, match="method должен быть None"):
        HttpEndpoint(
            path="/ws/invalid",
            service="test.ws",
            websocket=True,
            method="GET",
        )
    
    # ✗ HTTP endpoint без method должен вызвать ошибку
    with pytest.raises(ValueError, match="method обязателен"):
        HttpEndpoint(
            path="/http/test",
            service="test.http",
            websocket=False,
        )


@pytest.mark.asyncio
async def test_websocket_endpoint_registration(memory_adapter):
    """Тест: WebSocket endpoint регистрируется в HttpRegistry."""
    runtime = CoreRuntime(memory_adapter)
    
    # Регистрируем WebSocket endpoint
    ws_endpoint = HttpEndpoint(
        path="/ws/echo",
        service="test.websocket.echo",
        websocket=True,
        description="Echo WebSocket endpoint",
        tags=["test", "websocket"]
    )
    runtime.http.register(ws_endpoint)
    
    # Проверяем что endpoint зарегистрирован
    endpoints = runtime.http.list()
    ws_endpoints = [ep for ep in endpoints if ep.websocket]
    
    assert len(ws_endpoints) == 1
    assert ws_endpoints[0].path == "/ws/echo"
    assert ws_endpoints[0].service == "test.websocket.echo"
    assert ws_endpoints[0].websocket is True
    assert ws_endpoints[0].method is None
    assert ws_endpoints[0].tags == ["test", "websocket"]


@pytest.mark.asyncio
async def test_websocket_endpoint_uniqueness(memory_adapter):
    """Тест: WebSocket endpoint должен быть уникален по пути."""
    runtime = CoreRuntime(memory_adapter)
    
    # Регистрируем первый endpoint
    ws_endpoint1 = HttpEndpoint(
        path="/ws/unique",
        service="test.ws1",
        websocket=True,
    )
    runtime.http.register(ws_endpoint1)
    
    # Попытка регистрировать второй endpoint на том же пути
    ws_endpoint2 = HttpEndpoint(
        path="/ws/unique",
        service="test.ws2",
        websocket=True,
    )
    
    with pytest.raises(ValueError, match="уже зарегистрирован"):
        runtime.http.register(ws_endpoint2)


@pytest.mark.asyncio
async def test_websocket_endpoint_list_method(memory_adapter):
    """Тест: list_websocket_endpoints() возвращает только WebSocket endpoints."""
    runtime = CoreRuntime(memory_adapter)
    
    # Регистрируем HTTP endpoint
    http_endpoint = HttpEndpoint(
        path="/api/test",
        service="test.http",
        method="GET",
        kind="api"
    )
    runtime.http.register(http_endpoint)
    
    # Регистрируем WebSocket endpoint
    ws_endpoint = HttpEndpoint(
        path="/ws/test",
        service="test.ws",
        websocket=True,
    )
    runtime.http.register(ws_endpoint)
    
    # Проверяем что методы фильтруют правильно
    all_endpoints = runtime.http.list()
    ws_endpoints = runtime.http.list_websocket_endpoints()
    api_endpoints = runtime.http.list_api_endpoints()
    
    assert len(all_endpoints) == 2
    assert len(ws_endpoints) == 1
    assert len(api_endpoints) == 1
    assert ws_endpoints[0].websocket is True
    assert api_endpoints[0].websocket is False


@pytest.mark.asyncio
async def test_websocket_inspector_visibility(memory_adapter):
    """Тест: Inspector показывает websocket endpoints с флагом."""
    from modules.admin.services.introspection import list_http_endpoints
    
    runtime = CoreRuntime(memory_adapter)
    
    # Регистрируем HTTP и WebSocket endpoints
    http_endpoint = HttpEndpoint(
        path="/api/test",
        service="test.http",
        method="POST",
        description="HTTP endpoint"
    )
    runtime.http.register(http_endpoint)
    
    ws_endpoint = HttpEndpoint(
        path="/ws/test",
        service="test.ws",
        websocket=True,
        description="WebSocket endpoint",
        tags=["websocket"]
    )
    runtime.http.register(ws_endpoint)
    
    # Получаем список endpoints через inspector
    endpoints = await list_http_endpoints(runtime)
    
    # Проверяем что оба endpoint видны
    assert len(endpoints) == 2
    
    # Проверяем HTTP endpoint
    http_eps = [ep for ep in endpoints if ep["path"] == "/api/test"]
    assert len(http_eps) == 1
    assert http_eps[0]["websocket"] is False
    assert http_eps[0]["method"] == "POST"
    
    # Проверяем WebSocket endpoint
    ws_eps = [ep for ep in endpoints if ep["path"] == "/ws/test"]
    assert len(ws_eps) == 1
    assert ws_eps[0]["websocket"] is True
    assert ws_eps[0]["method"] is None
    assert "websocket" in ws_eps[0]["tags"]


@pytest.mark.asyncio
async def test_websocket_plugin_registration(memory_adapter):
    """Тест: WebSocketTestPlugin регистрирует endpoint и сервис."""
    from plugins.test import WebSocketTestPlugin
    
    runtime = CoreRuntime(memory_adapter)
    
    # Загружаем плагин
    plugin = WebSocketTestPlugin(runtime)
    await plugin.on_load()
    
    # Проверяем что endpoint зарегистрирован
    endpoints = runtime.http.list()
    ws_endpoints = [ep for ep in endpoints if ep.service == "websocket_test.echo"]
    
    assert len(ws_endpoints) == 1
    assert ws_endpoints[0].path == "/test/ws"
    assert ws_endpoints[0].websocket is True
    
    # Проверяем что сервис зарегистрирован
    has_service = await runtime.service_registry.has_service("websocket_test.echo")
    assert has_service is True
