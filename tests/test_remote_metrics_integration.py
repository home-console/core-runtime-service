import asyncio
import json
import socket
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import TYPE_CHECKING

import pytest

from core.runtime import CoreRuntime
from core.plugin_manager import PluginManager
from plugins.remote_plugin_proxy import RemotePluginProxy
from tests.conftest import InMemoryStorageAdapter


class MockRemoteHandler(BaseHTTPRequestHandler):
    # Общие состояние сервера
    server_version = "MockRemote/0.1"

    def _set_json(self, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()

    def do_GET(self):
        if self.path == "/plugin/metadata":
            self._set_json()
            body = {
                "name": "remote_metrics",
                "type": "system",
                "mode": "remote",
                "version": "0.1.0",
                "description": "mock remote metrics",
                "services": [{"name": "metrics.report", "endpoint": "/metrics/report", "method": "POST"}],
            }
            self.wfile.write(json.dumps(body).encode())
            return
        if self.path == "/plugin/health":
            self._set_json()
            self.wfile.write(json.dumps({"status": "ok"}).encode())
            return
        if self.path == "/plugin/metrics":
            self._set_json()
            self.wfile.write(json.dumps({"metrics": self.server.metrics}).encode())
            return
        self._set_json(404)
        self.wfile.write(json.dumps({"error": "not found"}).encode())

    def do_POST(self):
        length = int(self.headers.get("content-length", 0))
        body = self.rfile.read(length).decode() if length else ""
        try:
            data = json.loads(body) if body else {}
        except Exception:
            data = {}
        if self.path == "/plugin/load":
            self.server.loaded = True
            self._set_json()
            self.wfile.write(json.dumps({"status": "ok"}).encode())
            return
        if self.path == "/plugin/start":
            self.server.started = True
            self._set_json()
            self.wfile.write(json.dumps({"status": "ok"}).encode())
            return
        if self.path == "/plugin/stop":
            self.server.started = False
            self._set_json()
            self.wfile.write(json.dumps({"status": "ok"}).encode())
            return
        if self.path == "/plugin/unload":
            self.server.loaded = False
            self.server.started = False
            self._set_json()
            self.wfile.write(json.dumps({"status": "ok"}).encode())
            return
        if self.path == "/metrics/report":
            # ожидаем payload: {"args":[], "kwargs":{...}}
            payload = data
            # логируем в список сервера
            self.server.metrics.append(payload.get("kwargs") or {})
            self._set_json()
            self.wfile.write(json.dumps({"status": "ok"}).encode())
            return
        self._set_json(404)
        self.wfile.write(json.dumps({"error": "not found"}).encode())

class MockHTTPServer(HTTPServer):
    """HTTPServer subclass with explicit attributes used by the tests/handler.

    Declaring and initializing these attributes prevents static type checkers
    (pylance/mypy) from complaining about unknown attributes on the server
    instance (metrics, loaded, started).
    """

    def __init__(self, server_address, RequestHandlerClass):
        super().__init__(server_address, RequestHandlerClass)
        self.metrics = []
        self.loaded = False
        self.started = False


if TYPE_CHECKING:
    # Для статических анализаторов: у обработчика `self.server` будет наш MockHTTPServer
    MockRemoteHandler.server: "MockHTTPServer"

@pytest.fixture
def mock_remote_server():
    # Поднять простой HTTP сервер на свободном порту
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    addr, port = sock.getsockname()
    sock.close()

    server = MockHTTPServer(("127.0.0.1", port), MockRemoteHandler)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield server, port

    server.shutdown()
    thread.join(timeout=1)


@pytest.mark.asyncio
async def test_remote_metrics_proxy_lifecycle_and_service(mock_remote_server):
    server, port = mock_remote_server
    base_url = f"http://127.0.0.1:{port}"

    # Инициализируем runtime
    runtime = CoreRuntime(InMemoryStorageAdapter())

    proxy = RemotePluginProxy(runtime, base_url)

    # Загрузка плагина — должен вызвать /plugin/metadata и /plugin/load
    await runtime.plugin_manager.load_plugin(proxy)

    # Убедиться, что сервис зарегистрирован
    assert runtime.service_registry.has_service("metrics.report")

    # Запуск плагина — вызывает /plugin/start
    await runtime.plugin_manager.start_plugin(proxy.metadata.name)

    # Вызов сервиса через proxy
    await runtime.service_registry.call("metrics.report", name="cpu", value=0.42, tags={"host": "test"})

    # Проверяем, что mock server получил вызов
    assert server.metrics, "Remote сервер не получил метрику"
    last = server.metrics[-1]
    assert last.get("name") == "cpu"
    assert abs(float(last.get("value")) - 0.42) < 1e-6
    assert last.get("tags", {}).get("host") == "test"

    # Остановим mock сервер чтобы симулировать падение remote
    server.shutdown()

    # Вызов сервиса теперь должен бросать ошибку, но Core остаётся живым
    with pytest.raises(Exception):
        await runtime.service_registry.call("metrics.report", name="mem", value=10, tags={})

    # Выгрузка плагина через менеджер — должна отрегистировать сервисы
    await runtime.plugin_manager.unload_plugin(proxy.metadata.name)
    assert not runtime.service_registry.has_service("metrics.report")
