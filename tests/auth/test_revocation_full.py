"""
Tests for modules/api/auth/revocation.py (coverage: 64% → 80%+)
"""
import pytest
import hashlib
from types import SimpleNamespace

from modules.api.auth.revocation import (
    revoke_api_key,
    revoke_session,
    revoke_refresh_token,
    is_revoked,
)
from modules.api.auth.constants import (
    AUTH_REVOKED_NAMESPACE,
    AUTH_API_KEYS_NAMESPACE,
    AUTH_SESSIONS_NAMESPACE,
    AUTH_REFRESH_TOKENS_NAMESPACE,
)


class FakeStorage:
    def __init__(self, raise_on_set=False):
        self._d = {}
        self.raise_on_set = raise_on_set

    async def get(self, ns, key):
        return self._d.get(ns, {}).get(key)

    async def set(self, ns, key, value):
        if self.raise_on_set:
            raise Exception("storage failure")
        self._d.setdefault(ns, {})[key] = value

    async def delete(self, ns, key):
        self._d.get(ns, {}).pop(key, None)


class FakeServiceRegistry:
    def __init__(self):
        self.calls = []

    async def call(self, *args, **kwargs):
        self.calls.append((args, kwargs))


@pytest.fixture
def rt():
    return SimpleNamespace(
        storage=FakeStorage(),
        service_registry=FakeServiceRegistry(),
    )


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


# ---------------------------------------------------------------------------
# revoke_api_key
# ---------------------------------------------------------------------------

class TestRevokeApiKey:

    @pytest.mark.asyncio
    async def test_stores_in_revoked_namespace(self, rt):
        await revoke_api_key(rt, "test-api-key-12345")
        entry = await rt.storage.get(AUTH_REVOKED_NAMESPACE, _sha("test-api-key-12345"))
        assert entry is not None
        assert entry["type"] == "api_key"

    @pytest.mark.asyncio
    async def test_deletes_from_active_keys(self, rt):
        await rt.storage.set(AUTH_API_KEYS_NAMESPACE, "test-api-key-12345", {"active": True})
        await revoke_api_key(rt, "test-api-key-12345")
        remaining = await rt.storage.get(AUTH_API_KEYS_NAMESPACE, "test-api-key-12345")
        assert remaining is None

    @pytest.mark.asyncio
    async def test_handles_storage_error_without_raise(self):
        rt = SimpleNamespace(
            storage=FakeStorage(raise_on_set=True),
            service_registry=FakeServiceRegistry(),
        )
        # Should not raise
        await revoke_api_key(rt, "any-key")

    @pytest.mark.asyncio
    async def test_revoked_entry_has_revoked_at(self, rt):
        import time
        before = time.time()
        await revoke_api_key(rt, "my-key")
        entry = await rt.storage.get(AUTH_REVOKED_NAMESPACE, _sha("my-key"))
        assert entry["revoked_at"] >= before


# ---------------------------------------------------------------------------
# revoke_session
# ---------------------------------------------------------------------------

class TestRevokeSession:

    @pytest.mark.asyncio
    async def test_stores_in_revoked_namespace(self, rt):
        await revoke_session(rt, "session-abc-123")
        entry = await rt.storage.get(AUTH_REVOKED_NAMESPACE, _sha("session-abc-123"))
        assert entry is not None
        assert entry["type"] == "session"

    @pytest.mark.asyncio
    async def test_deletes_from_active_sessions(self, rt):
        await rt.storage.set(AUTH_SESSIONS_NAMESPACE, "session-abc-123", {"user_id": "u1"})
        await revoke_session(rt, "session-abc-123")
        remaining = await rt.storage.get(AUTH_SESSIONS_NAMESPACE, "session-abc-123")
        assert remaining is None

    @pytest.mark.asyncio
    async def test_handles_storage_error_without_raise(self):
        rt = SimpleNamespace(
            storage=FakeStorage(raise_on_set=True),
            service_registry=FakeServiceRegistry(),
        )
        await revoke_session(rt, "any-session")

    @pytest.mark.asyncio
    async def test_entry_type_is_session(self, rt):
        await revoke_session(rt, "session-xyz")
        entry = await rt.storage.get(AUTH_REVOKED_NAMESPACE, _sha("session-xyz"))
        assert entry["type"] == "session"


# ---------------------------------------------------------------------------
# revoke_refresh_token
# ---------------------------------------------------------------------------

class TestRevokeRefreshToken:

    @pytest.mark.asyncio
    async def test_stores_in_revoked_namespace(self, rt):
        await revoke_refresh_token(rt, "refresh-tok-abc")
        entry = await rt.storage.get(AUTH_REVOKED_NAMESPACE, _sha("refresh-tok-abc"))
        assert entry is not None
        assert entry["type"] == "refresh_token"

    @pytest.mark.asyncio
    async def test_deletes_from_active_tokens(self, rt):
        await rt.storage.set(AUTH_REFRESH_TOKENS_NAMESPACE, "refresh-tok-abc", {"user_id": "u1"})
        await revoke_refresh_token(rt, "refresh-tok-abc")
        remaining = await rt.storage.get(AUTH_REFRESH_TOKENS_NAMESPACE, "refresh-tok-abc")
        assert remaining is None

    @pytest.mark.asyncio
    async def test_handles_storage_error_without_raise(self):
        rt = SimpleNamespace(
            storage=FakeStorage(raise_on_set=True),
            service_registry=FakeServiceRegistry(),
        )
        await revoke_refresh_token(rt, "any-token")

    @pytest.mark.asyncio
    async def test_entry_type_is_refresh_token(self, rt):
        await revoke_refresh_token(rt, "tok-123")
        entry = await rt.storage.get(AUTH_REVOKED_NAMESPACE, _sha("tok-123"))
        assert entry["type"] == "refresh_token"


# ---------------------------------------------------------------------------
# is_revoked
# ---------------------------------------------------------------------------

class TestIsRevoked:

    @pytest.mark.asyncio
    async def test_returns_true_for_revoked_api_key(self, rt):
        await revoke_api_key(rt, "revoked-key")
        assert await is_revoked(rt, "revoked-key", "api_key") is True

    @pytest.mark.asyncio
    async def test_returns_false_for_not_revoked(self, rt):
        assert await is_revoked(rt, "fresh-key", "api_key") is False

    @pytest.mark.asyncio
    async def test_returns_false_when_type_mismatch(self, rt):
        await revoke_session(rt, "some-session")
        # Check as api_key — type mismatch → False
        assert await is_revoked(rt, "some-session", "api_key") is False

    @pytest.mark.asyncio
    async def test_returns_false_for_non_dict_entry(self, rt):
        revoked_key = _sha("bad-entry")
        await rt.storage.set(AUTH_REVOKED_NAMESPACE, revoked_key, "not-a-dict")
        assert await is_revoked(rt, "bad-entry", "api_key") is False

    @pytest.mark.asyncio
    async def test_returns_true_on_storage_exception_fail_closed(self):
        bad_storage = SimpleNamespace(
            get=AsyncMock_ify(Exception("broken"))
        )
        rt = SimpleNamespace(storage=bad_storage, service_registry=FakeServiceRegistry())
        assert await is_revoked(rt, "x", "api_key") is True

    @pytest.mark.asyncio
    async def test_session_revoked_true(self, rt):
        await revoke_session(rt, "session-test-id")
        assert await is_revoked(rt, "session-test-id", "session") is True

    @pytest.mark.asyncio
    async def test_refresh_token_revoked_true(self, rt):
        await revoke_refresh_token(rt, "refresh-test-token")
        assert await is_revoked(rt, "refresh-test-token", "refresh_token") is True

    @pytest.mark.asyncio
    async def test_returns_false_for_none_entry_type(self, rt):
        revoked_key = _sha("no-type-key")
        await rt.storage.set(AUTH_REVOKED_NAMESPACE, revoked_key, {"revoked_at": 123.0})
        assert await is_revoked(rt, "no-type-key", "api_key") is False


def AsyncMock_ify(exc):
    """Return a storage stub that raises exc on get."""
    class _S:
        async def get(self, *a, **kw):
            raise exc
        async def set(self, *a, **kw):
            raise exc
        async def delete(self, *a, **kw):
            pass
    return _S()
