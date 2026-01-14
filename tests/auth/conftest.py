import pytest
from types import SimpleNamespace


class FakeStorage:
    def __init__(self):
        self._data = {}

    async def get(self, namespace, key):
        return self._data.get(namespace, {}).get(key)

    async def set(self, namespace, key, value):
        self._data.setdefault(namespace, {})[key] = value

    async def delete(self, namespace, key):
        ns = self._data.get(namespace)
        if ns:
            ns.pop(key, None)


class FakeServiceRegistry:
    async def call(self, *args, **kwargs):
        return None


class FakeRuntime:
    def __init__(self):
        self.storage = FakeStorage()
        self.service_registry = FakeServiceRegistry()


@pytest.fixture
def runtime():
    return FakeRuntime()
