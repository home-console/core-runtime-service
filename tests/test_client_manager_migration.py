"""
Тест миграции client-manager на HttpRegistry.

Проверяет что:
1. Endpoints регистрируются через HttpRegistry
2. Сервисы регистрируются через service_registry
3. WebSocket endpoints видны в inspector
4. Плагин не запускает собственный uvicorn сервер
"""

import pytest
import asyncio
import sys
from pathlib import Path

# Добавляем путь к client-manager-service plugin'у
CLIENT_MANAGER_PATH = Path(__file__).parent.parent / "plugins" / "client-manager-service"
if str(CLIENT_MANAGER_PATH) not in sys.path:
    sys.path.insert(0, str(CLIENT_MANAGER_PATH))

from core.runtime import CoreRuntime
from tests.conftest import InMemoryStorageAdapter
from core.storage_port import CoreStoragePort
from core.state_engine import StateEngine


@pytest.mark.asyncio
async def test_client_manager_endpoints_registered():
    """Тест: client-manager регистрирует endpoints через HttpRegistry."""
    _adapter = InMemoryStorageAdapter()

    memory_adapter = CoreStoragePort(_adapter, StateEngine())
    runtime = CoreRuntime(memory_adapter)
    
    # Импортируем плагин
    from plugin import ClientManagerPlugin
    
    # Создаём и загружаем плагин
    plugin = ClientManagerPlugin(runtime)
    await plugin.on_load()
    
    # Проверяем что endpoints зарегистрированы
    endpoints = runtime.http.list()
    
    # Ищем endpoints client-manager
    cm_endpoints = [ep for ep in endpoints if "client-manager" in ep.path]
    
    assert len(cm_endpoints) > 0, "client-manager endpoints должны быть зарегистрированы"
    
    # Проверяем WebSocket endpoints
    ws_endpoints = [ep for ep in cm_endpoints if ep.websocket]
    assert len(ws_endpoints) >= 2, "Должны быть оба WebSocket endpoints (ws и admin/ws)"
    
    # Проверяем что хотя бы один из них это /client-manager/ws
    assert any(ep.path == "/client-manager/ws" for ep in ws_endpoints), \
        "WebSocket endpoint /client-manager/ws должен быть зарегистрирован"
    
    # Проверяем REST endpoints
    rest_endpoints = [ep for ep in cm_endpoints if not ep.websocket]
    assert len(rest_endpoints) > 0, "REST endpoints должны быть зарегистрированы"
    
    # Проверяем что есть endpoint для клиентов
    assert any("clients" in ep.path for ep in rest_endpoints), \
        "Endpoint для управления клиентами должен быть"


@pytest.mark.asyncio
async def test_client_manager_services_registered():
    """Тест: client-manager регистрирует сервисы через service_registry."""
    _adapter = InMemoryStorageAdapter()

    memory_adapter = CoreStoragePort(_adapter, StateEngine())
    runtime = CoreRuntime(memory_adapter)
    
    # Импортируем плагин
    from plugin import ClientManagerPlugin
    
    # Создаём и загружаем плагин
    plugin = ClientManagerPlugin(runtime)
    await plugin.on_load()
    
    # Проверяем что сервисы зарегистрированы
    services = [
        "client_manager.list_clients",
        "client_manager.get_client",
        "client_manager.execute_command",
        "client_manager.websocket",
        "client_manager.admin_websocket",
    ]
    
    for service in services:
        has_service = await runtime.service_registry.has_service(service)
        assert has_service, f"Сервис {service} должен быть зарегистрирован"


@pytest.mark.asyncio
async def test_client_manager_no_internal_server():
    """Тест: client-manager НЕ запускает собственный uvicorn сервер."""
    _adapter = InMemoryStorageAdapter()

    memory_adapter = CoreStoragePort(_adapter, StateEngine())
    runtime = CoreRuntime(memory_adapter)
    
    # Импортируем плагин
    from plugin import ClientManagerPlugin
    
    # Создаём и загружаем плагин
    plugin = ClientManagerPlugin(runtime)
    await plugin.on_load()
    
    # Проверяем что нет uvicorn сервера
    assert not hasattr(plugin, 'server') or plugin.server is None, \
        "Плагин не должен иметь собственный uvicorn сервер"
    assert not hasattr(plugin, 'server_task') or plugin.server_task is None, \
        "Плагин не должен иметь задачу сервера"


@pytest.mark.asyncio
async def test_client_manager_websocket_endpoints_in_inspector():
    """Тест: WebSocket endpoints видны в inspector как WebSocket'ы."""
    from modules.admin.services.introspection import list_http_endpoints
    
    _adapter = InMemoryStorageAdapter()

    
    memory_adapter = CoreStoragePort(_adapter, StateEngine())
    runtime = CoreRuntime(memory_adapter)
    
    # Импортируем плагин
    from plugin import ClientManagerPlugin
    
    # Создаём и загружаем плагин
    plugin = ClientManagerPlugin(runtime)
    await plugin.on_load()
    
    # Получаем endpoints через inspector
    endpoints = await list_http_endpoints(runtime)
    
    # Ищем client-manager endpoints
    cm_endpoints = [ep for ep in endpoints if "client-manager" in ep.get("path", "")]
    
    # Проверяем что есть WebSocket endpoints
    ws_eps = [ep for ep in cm_endpoints if ep.get("websocket") is True]
    assert len(ws_eps) >= 2, "Inspector должен показывать оба WebSocket endpoint'а"
    
    # Проверяем что method=null для WebSocket'ов
    for ep in ws_eps:
        assert ep.get("method") is None, \
            f"WebSocket endpoint {ep['path']} должен иметь method=null"
