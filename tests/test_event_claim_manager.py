import pytest

from core.messaging_claim_manager import EventBusClaimManager


class _StorageWithAdapter:
    def __init__(self, adapter):
        self._adapter = adapter
        self._data = {}

    async def get(self, namespace, key):
        return self._data.get((namespace, key))

    async def set(self, namespace, key, value):
        self._data[(namespace, key)] = value


@pytest.mark.asyncio
async def test_claim_event_prefers_sqlite_atomic_when_run_atomic_present():
    called = {"atomic": 0}

    class Adapter:
        def run_atomic(self, fn):
            called["atomic"] += 1

            # Provide minimal conn with execute(). rowcount>0 path
            class _Cursor:
                rowcount = 1

            class _Conn:
                def execute(self, *args, **kwargs):
                    return _Cursor()

            return fn(_Conn(), self)

    storage = _StorageWithAdapter(Adapter())
    mgr = EventBusClaimManager(storage)
    ok = await mgr.claim_event("evt-1", "w1")
    assert ok is True
    assert called["atomic"] == 1


@pytest.mark.asyncio
async def test_claim_event_prefers_postgres_atomic_when_pool_present():
    called = {"fetchrow": 0}

    class _Conn:
        async def fetchrow(self, *args, **kwargs):
            called["fetchrow"] += 1
            return {"ok": 1}

    class _Acquire:
        async def __aenter__(self):
            return _Conn()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Pool:
        def acquire(self):
            return _Acquire()

    class Adapter:
        def _get_pool(self):
            return _Pool()

    storage = _StorageWithAdapter(Adapter())
    mgr = EventBusClaimManager(storage)
    ok = await mgr.claim_event("evt-2", "w2")
    assert ok is True
    assert called["fetchrow"] == 1


@pytest.mark.asyncio
async def test_claim_event_falls_back_without_known_adapter_features():
    class Adapter:
        pass

    storage = _StorageWithAdapter(Adapter())
    mgr = EventBusClaimManager(storage)

    # No event exists in fallback storage: should return False
    ok = await mgr.claim_event("evt-x", "w")
    assert ok is False

