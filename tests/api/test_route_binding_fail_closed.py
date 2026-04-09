"""
Integration tests for route_binding fail-closed policy (Phase 2 & 3).

Проверяют, что bind_routes() падает с RuntimeError при попытке
зарегистрировать endpoint без auth_config.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock
from fastapi import FastAPI

from core.http.models import HttpEndpoint, EndpointAuthConfig
from core.http.registry import HttpRegistry
from modules.api.route_binding import bind_routes


def _make_mock_runtime(*endpoints: HttpEndpoint):
    """Создать mock runtime с http registry и service_registry."""
    http_reg = HttpRegistry()
    for ep in endpoints:
        http_reg.register(ep)

    # Mock service_registry — нужен для bind_routes (has_service, call, etc.)
    svc_reg = MagicMock()
    svc_reg.has_service = AsyncMock(return_value=True)
    svc_reg.call = AsyncMock(return_value={"ok": True})
    svc_reg.call_without_timeout = AsyncMock(return_value={"ok": True})
    svc_reg.get_auth_config_sync = MagicMock(return_value=None)

    runtime = MagicMock()
    runtime.http = http_reg
    runtime.service_registry = svc_reg

    return runtime


class TestFailClosedOnMissingAuthConfig:
    """Тесты fail-closed политики: endpoint без auth_config → RuntimeError."""

    def test_http_endpoint_without_auth_config_raises(self):
        """Тест: HTTP endpoint без auth_config вызывает RuntimeError при bind."""
        ep = HttpEndpoint(
            method="GET",
            path="/api/v1/test",
            service="test.service",
            description="No auth config",
        )
        runtime = _make_mock_runtime(ep)
        app = FastAPI()

        with pytest.raises(RuntimeError, match="auth_config"):
            bind_routes(runtime, app)

    def test_ws_endpoint_without_auth_config_raises(self):
        """Тест: WS endpoint без auth_config вызывает RuntimeError при bind."""
        ep = HttpEndpoint(
            path="/api/ws/test",
            service="test.ws_service",
            websocket=True,
            description="No auth config WS",
        )
        runtime = _make_mock_runtime(ep)
        app = FastAPI()

        with pytest.raises(RuntimeError, match="auth_config"):
            bind_routes(runtime, app)

    def test_mixed_endpoints_all_must_have_auth_config(self):
        """Тест: хотя бы один endpoint без auth_config → RuntimeError."""
        ep_good = HttpEndpoint(
            method="GET",
            path="/api/v1/good",
            service="test.good",
            description="Has auth config",
            auth_config=EndpointAuthConfig(required_scopes=["admin.read"]),
        )
        ep_bad = HttpEndpoint(
            method="POST",
            path="/api/v1/bad",
            service="test.bad",
            description="No auth config",
        )
        runtime = _make_mock_runtime(ep_good, ep_bad)
        app = FastAPI()

        with pytest.raises(RuntimeError, match="auth_config"):
            bind_routes(runtime, app)

    def test_error_message_lists_offending_endpoints(self):
        """Тест: сообщение об ошибке содержит список endpoint'ов без auth_config."""
        ep = HttpEndpoint(
            method="DELETE",
            path="/admin/v1/resources/{id}",
            service="admin.v1.resources.delete",
            description="No auth config",
        )
        runtime = _make_mock_runtime(ep)
        app = FastAPI()

        with pytest.raises(RuntimeError) as exc_info:
            bind_routes(runtime, app)

        msg = str(exc_info.value)
        assert "auth_config" in msg
        assert "DELETE /admin/v1/resources/{id}" in msg
        assert "admin.v1.resources.delete" in msg


class TestFailClosedWithAuthConfig:
    """Тесты: endpoint'ы с auth_config биндятся успешно."""

    def test_http_endpoint_with_required_scopes_binds(self):
        """Тест: HTTP endpoint с required_scopes биндится успешно."""
        ep = HttpEndpoint(
            method="GET",
            path="/api/v1/devices",
            service="product_api.v1.devices.list",
            description="List devices",
            auth_config=EndpointAuthConfig(required_scopes=["devices.read"]),
        )
        runtime = _make_mock_runtime(ep)
        app = FastAPI()

        # Не должно бросать
        bind_routes(runtime, app)

        # Проверяем что маршрут добавлен
        routes = [r.path for r in app.routes]
        assert "/api/v1/devices" in routes

    def test_http_endpoint_with_public_binds(self):
        """Тест: HTTP endpoint с public=True биндится успешно."""
        ep = HttpEndpoint(
            method="GET",
            path="/auth/v1/bootstrap",
            service="auth.bootstrap",
            description="Bootstrap status",
            auth_config=EndpointAuthConfig(public=True),
        )
        runtime = _make_mock_runtime(ep)
        app = FastAPI()

        bind_routes(runtime, app)

        routes = [r.path for r in app.routes]
        assert "/auth/v1/bootstrap" in routes

    def test_ws_endpoint_with_auth_config_binds(self):
        """Тест: WS endpoint с auth_config биндится успешно."""
        ep = HttpEndpoint(
            path="/admin/v1/ssh/ws/{session_id}",
            service="admin.v1.ssh.ws",
            websocket=True,
            description="SSH WebSocket",
            auth_config=EndpointAuthConfig(required_scopes=["admin.write"]),
        )
        runtime = _make_mock_runtime(ep)
        app = FastAPI()

        # Не должно бросать
        bind_routes(runtime, app)

    def test_mixed_http_and_ws_all_with_auth_binds(self):
        """Тест: mix HTTP + WS, все с auth_config → успешно."""
        eps = [
            HttpEndpoint(
                method="GET", path="/api/v1/list", service="test.list",
                description="List", auth_config=EndpointAuthConfig(required_scopes=["admin.read"]),
            ),
            HttpEndpoint(
                method="POST", path="/api/v1/create", service="test.create",
                description="Create", auth_config=EndpointAuthConfig(required_scopes=["admin.write"]),
            ),
            HttpEndpoint(
                path="/ws/terminal/{id}", service="test.ws",
                websocket=True, description="WS",
                auth_config=EndpointAuthConfig(required_scopes=["admin.write"]),
            ),
        ]
        runtime = _make_mock_runtime(*eps)
        app = FastAPI()

        # Не должно бросать
        bind_routes(runtime, app)

        routes = [r.path for r in app.routes]
        assert "/api/v1/list" in routes
        assert "/api/v1/create" in routes
