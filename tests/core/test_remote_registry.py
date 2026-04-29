"""Тесты RemoteServiceRegistry (без реального HTTP)."""

import json

import httpx
import pytest

from core.ports import IServiceRegistry
from core.service.remote_registry import RemoteServiceRegistry


def test_remote_registry_implements_interface():
    reg = RemoteServiceRegistry(base_url="http://localhost", api_key="test")
    assert isinstance(reg, IServiceRegistry)


@pytest.mark.asyncio
async def test_call_success(monkeypatch):
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/internal/v1/services/devices.get"
        assert request.headers.get("authorization") == "Bearer key"
        body = json.loads(request.content.decode("utf-8"))
        assert body["kwargs"]["device_id"] == "abc"
        return httpx.Response(200, json={"result": {"id": "abc"}, "error": None})

    transport = httpx.MockTransport(handler)

    real_client = httpx.AsyncClient(
        base_url="http://core:8000",
        headers={"Authorization": "Bearer key"},
        timeout=30.0,
        transport=transport,
    )

    def _client_factory(*args, **kwargs):
        return real_client

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory)

    reg = RemoteServiceRegistry(base_url="http://core:8000", api_key="key")
    await reg.start()
    result = await reg.call("devices.get", device_id="abc")
    assert result == {"id": "abc"}
    await reg.stop()


@pytest.mark.asyncio
async def test_call_service_not_found(monkeypatch):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not found"})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient(
        base_url="http://core:8000",
        headers={"Authorization": "Bearer key"},
        timeout=30.0,
        transport=transport,
    )

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: real_client)

    reg = RemoteServiceRegistry(base_url="http://core:8000", api_key="key")
    await reg.start()
    with pytest.raises(ValueError, match="не найден"):
        await reg.call("unknown")
    await reg.stop()


@pytest.mark.asyncio
async def test_factory_returns_local_by_default(monkeypatch):
    monkeypatch.delenv("SERVICE_REGISTRY_BACKEND", raising=False)
    from core.service.registry_factory import create_service_registry
    from core.service.registry import ServiceRegistry

    reg = create_service_registry()
    assert isinstance(reg, ServiceRegistry)

