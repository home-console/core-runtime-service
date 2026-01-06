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
