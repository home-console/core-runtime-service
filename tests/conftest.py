import sys
import os
import pathlib
import pytest

# Ensure repository root is on sys.path so packages (adapters, core, plugins) import correctly
ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.storage_adapter import StorageAdapter
from core.storage_port import CoreStoragePort
from core.state_engine import StateEngine


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

    async def list_namespaces(self) -> list[str]:
        # Return sorted list of namespaces present in memory
        return sorted(list(self._data.keys()))

    async def clear_namespace(self, namespace: str) -> None:
        self._data.pop(namespace, None)

    async def close(self) -> None:
        self.closed = True

    async def batch_set(self, namespace: str, items: dict[str, dict]) -> None:
        ns = self._data.setdefault(namespace, {})
        for k, v in items.items():
            ns[k] = v

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def transaction(self):
        # In-memory adapter: transaction is a no-op
        try:
            yield
        finally:
            pass

    async def iter_namespace(self, namespace: str, batch_size: int = 100):
        for key, value in self._data.get(namespace, {}).items():
            yield key, value


@pytest.fixture
def memory_adapter():
    adapter = InMemoryStorageAdapter()
    state_engine = StateEngine()
    return CoreStoragePort(adapter, state_engine)


# ──────────────────────────────────────────────────────────────────────────────
# Prevent .env pollution: some tests import `main` which loads .env into
# os.environ (DEBUG=1, RUNTIME_STORAGE_MODE=dual, etc.).
# This autouse fixture saves and restores critical env vars around each test.
# ──────────────────────────────────────────────────────────────────────────────
_POLLUTABLE_VARS = (
    "DEBUG",
    "RUNTIME_STORAGE_MODE",
    "STORAGE_SKIP_ROOT_VERIFY",
    "RUNTIME_VAULT_STORAGE_TYPE",
    "RUNTIME_VAULT_DB_PATH",
    "RUNTIME_INSTALL_PLUGIN_DEPS",
)

@pytest.fixture(scope="session", autouse=True)
def _clean_env_session():
    """At session start, remove env vars loaded from .env so they don't pollute tests."""
    # Capture vars as they are before session tests run (may be set by main.py import)
    pre_session = {k: os.environ.get(k) for k in _POLLUTABLE_VARS}
    # Remove them so each test starts clean
    for k in _POLLUTABLE_VARS:
        os.environ.pop(k, None)
    yield
    # Restore original state at end of session
    for k, v in pre_session.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture(autouse=True)
def _restore_env():
    """Save and restore environment variables that .env loading may pollute.

    main.py loads .env on import, which sets DEBUG=1, RUNTIME_STORAGE_MODE=dual,
    etc. These variables must not leak between tests.
    """
    # Before each test: capture current state
    saved = {k: os.environ.get(k) for k in _POLLUTABLE_VARS}
    yield
    # After each test: restore to saved state
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
