from unittest.mock import AsyncMock

import pytest
from core.runtime.config import Config
from core.orchestration import NullOrchestrationBackend
from core.runtime import CoreRuntime
from core.runtime.runtime import CoreRuntime
from core.runtime.runtime_module import RuntimeModule
from modules.policy.engine import PolicyEngine


class DummyAdapter:
    def __init__(self):
        self.closed = False

    async def get(self, namespace, key):
        return None

    async def set(self, namespace, key, value):
        pass

    async def delete(self, namespace, key):
        return False

    async def list_keys(self, namespace):
        return []

    async def clear_namespace(self, namespace):
        pass

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_core_start_stop_shutdown(memory_adapter, monkeypatch):
    monkeypatch.setenv("TEST_MODE", "1")
    runtime = CoreRuntime(memory_adapter)
    assert runtime.is_running is False

    await runtime.start()
    assert runtime.is_running is True
    # runtime.state_engine should have runtime.status == 'running'
    assert await runtime.state_engine.get("runtime.status") == "running"

    await runtime.stop()
    assert runtime.is_running is False
    assert await runtime.state_engine.get("runtime.status") == "stopped"

    # shutdown should clear components
    await runtime.shutdown()
    assert await runtime.state_engine.keys() == []


@pytest.mark.asyncio
async def test_health_check_healthy(memory_adapter, monkeypatch):
    """Тест health_check для здорового runtime."""
    monkeypatch.setenv("TEST_MODE", "1")
    runtime = CoreRuntime(memory_adapter)
    await runtime.start()

    health = await runtime.health_check()

    assert "status" in health
    assert "uptime" in health
    assert "checks" in health
    assert health["status"] in ("healthy", "ok", "degraded")
    assert health["uptime"] >= 0
    assert "storage" in health["checks"]

    await runtime.stop()


@pytest.mark.asyncio
async def test_health_check_before_start(memory_adapter, monkeypatch):
    """Тест health_check до старта runtime."""
    monkeypatch.setenv("TEST_MODE", "1")
    runtime = CoreRuntime(memory_adapter)

    health = await runtime.health_check()

    assert "status" in health
    assert "uptime" in health
    assert health["uptime"] == 0  # Не запущен


@pytest.mark.asyncio
async def test_get_metrics(memory_adapter, monkeypatch):
    """Тест get_metrics для runtime."""
    monkeypatch.setenv("TEST_MODE", "1")
    runtime = CoreRuntime(memory_adapter)
    await runtime.start()

    metrics = await runtime.get_metrics()

    assert "uptime" in metrics
    assert metrics["uptime"] >= 0
    assert "plugins" in metrics
    assert "modules" in metrics
    assert "services" in metrics
    assert "storage" in metrics
    assert "http_endpoints" in metrics

    # Проверяем структуру метрик
    assert isinstance(metrics["plugins"], dict)
    assert isinstance(metrics["modules"], dict)
    assert isinstance(metrics["services"], dict)
    assert isinstance(metrics["storage"], dict)
    assert isinstance(metrics["http_endpoints"], dict)

    await runtime.stop()


@pytest.mark.asyncio
async def test_runtime_uses_configured_null_orchestration_backend(
    memory_adapter, monkeypatch
):
    """Runtime должен уметь отключать orchestration через config."""
    monkeypatch.setenv("TEST_MODE", "1")
    config = Config(orchestration_backend="none")
    runtime = CoreRuntime(memory_adapter, config=config)

    assert isinstance(runtime.orchestration_service._backend, NullOrchestrationBackend)


@pytest.mark.asyncio
async def test_runtime_accepts_injected_policy_engine(memory_adapter, monkeypatch):
    """Runtime должен принимать PolicyEngine через DI, а не только создавать сам."""
    monkeypatch.setenv("TEST_MODE", "1")
    engine = PolicyEngine()
    runtime = CoreRuntime(memory_adapter, policy_engine=engine)

    assert runtime.policy_engine is engine


@pytest.mark.asyncio
async def test_runtime_runs_transport_runner(memory_adapter, monkeypatch):
    monkeypatch.setenv("TEST_MODE", "1")
    runtime = CoreRuntime(memory_adapter)

    class DummyTransportModule(RuntimeModule):
        @property
        def name(self) -> str:
            return "dummy_transport"

        async def register(self) -> None:
            pass

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def run_transport(self, runtime_obj) -> None:
            runtime_obj._transport_called = True

    await runtime.module_manager.register(DummyTransportModule(runtime))
    runtime.start = AsyncMock()
    runtime.shutdown = AsyncMock()

    await runtime.run()

    assert getattr(runtime, "_transport_called", False) is True
    runtime.start.assert_awaited_once()
    runtime.shutdown.assert_awaited_once()
