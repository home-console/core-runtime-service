import pytest

from core.runtime import CoreRuntime
from core.state_engine import StateEngine


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
async def test_core_start_stop_shutdown(memory_adapter):
    runtime = CoreRuntime(memory_adapter)
    assert runtime.is_running is False

    await runtime.start()
    assert runtime.is_running is True
    # runtime.state_engine should have runtime.status == 'running'
    assert await runtime.state_engine.get('runtime.status') == 'running'

    await runtime.stop()
    assert runtime.is_running is False
    assert await runtime.state_engine.get('runtime.status') == 'stopped'

    # shutdown should clear components
    await runtime.shutdown()
    assert await runtime.state_engine.keys() == []


@pytest.mark.asyncio
async def test_health_check_healthy(memory_adapter):
    """Тест health_check для здорового runtime."""
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
async def test_health_check_before_start(memory_adapter):
    """Тест health_check до старта runtime."""
    runtime = CoreRuntime(memory_adapter)
    
    health = await runtime.health_check()
    
    assert "status" in health
    assert "uptime" in health
    assert health["uptime"] == 0  # Не запущен


@pytest.mark.asyncio
async def test_get_metrics(memory_adapter):
    """Тест get_metrics для runtime."""
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
