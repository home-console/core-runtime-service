import sys
import pathlib
import pytest

# Ensure repository root is on sys.path so packages (adapters, core, plugins) import correctly
ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.storage_adapter import StorageAdapter


class InMemoryStorageAdapter(StorageAdapter):
    def __init__(self):
        self._data: dict[str, dict[str, dict]] = {}
        self.closed = False

    async def get(self, namespace: str, key: str):
        return self._data.get(namespace, {}).get(key)

    async def set(self, namespace: str, key: str, value: dict):
        self._data.setdefault(namespace, {})[key] = value

    async def delete(self, namespace: str, key: str) -> bool:
        ns = self._data.get(namespace, {})
        if key in ns:
            del ns[key]
            return True
        return False

    async def list_keys(self, namespace: str) -> list[str]:
        return list(self._data.get(namespace, {}).keys())

    async def clear_namespace(self, namespace: str) -> None:
        self._data.pop(namespace, None)

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def memory_adapter():
    return InMemoryStorageAdapter()
