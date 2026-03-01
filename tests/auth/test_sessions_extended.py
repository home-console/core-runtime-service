"""
Tests for modules/api/auth/sessions.py (coverage: 67% → 80%+)
"""
import pytest
import time
from types import SimpleNamespace

from modules.api.auth.sessions import validate_session, create_session
from modules.api.auth.constants import (
    AUTH_SESSIONS_NAMESPACE,
    AUTH_USERS_NAMESPACE,
    AUTH_REVOKED_NAMESPACE,
)


class FakeStorage:
    def __init__(self):
        self._d = {}

    async def get(self, ns, key):
        return self._d.get(ns, {}).get(key)

    async def set(self, ns, key, value):
        self._d.setdefault(ns, {})[key] = value

    async def delete(self, ns, key):
        self._d.get(ns, {}).pop(key, None)


class FakeServiceRegistry:
    async def call(self, *args, **kwargs):
        return None


@pytest.fixture
def rt():
    return SimpleNamespace(
        storage=FakeStorage(),
        service_registry=FakeServiceRegistry(),
    )


async def _prepare_user(rt, user_id="u1", scopes=None, is_admin=False):
    await rt.storage.set(AUTH_USERS_NAMESPACE, user_id, {
        "user_id": user_id,
        "scopes": scopes or ["devices.read"],
        "is_admin": is_admin,
    })


async def _prepare_session(rt, session_id="sess1", user_id="u1", expires_offset=3600, last_used=0):
    await rt.storage.set(AUTH_SESSIONS_NAMESPACE, session_id, {
        "user_id": user_id,
        "expires_at": time.time() + expires_offset,
        "last_used": last_used or (time.time() - 120),  # 2 min ago by default
    })


# ---------------------------------------------------------------------------
# validate_session
# ---------------------------------------------------------------------------

class TestValidateSession:

    @pytest.mark.asyncio
    async def test_empty_session_id_returns_none(self, rt):
        assert await validate_session(rt, "") is None

    @pytest.mark.asyncio
    async def test_blank_session_id_returns_none(self, rt):
        assert await validate_session(rt, "   ") is None

    @pytest.mark.asyncio
    async def test_valid_session_returns_context(self, rt):
        await _prepare_user(rt)
        await _prepare_session(rt)
        ctx = await validate_session(rt, "sess1")
        assert ctx is not None
        assert ctx.user_id == "u1"
        assert ctx.source == "session"

    @pytest.mark.asyncio
    async def test_returns_none_when_session_missing(self, rt):
        result = await validate_session(rt, "nonexistent-session")
        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_session_data_structure_returns_none(self, rt):
        """session_data is not a dict → returns None"""
        await rt.storage.set(AUTH_SESSIONS_NAMESPACE, "bad-sess", "not-a-dict")
        result = await validate_session(rt, "bad-sess")
        assert result is None

    @pytest.mark.asyncio
    async def test_expired_session_returns_none(self, rt):
        await _prepare_user(rt)
        await rt.storage.set(AUTH_SESSIONS_NAMESPACE, "expired-sess", {
            "user_id": "u1",
            "expires_at": time.time() - 1000,
        })
        result = await validate_session(rt, "expired-sess")
        assert result is None

    @pytest.mark.asyncio
    async def test_expired_session_gets_deleted(self, rt):
        await _prepare_user(rt)
        await rt.storage.set(AUTH_SESSIONS_NAMESPACE, "expired-sess2", {
            "user_id": "u1",
            "expires_at": time.time() - 1000,
        })
        await validate_session(rt, "expired-sess2")
        remaining = await rt.storage.get(AUTH_SESSIONS_NAMESPACE, "expired-sess2")
        assert remaining is None

    @pytest.mark.asyncio
    async def test_no_user_id_in_session_returns_none(self, rt):
        await rt.storage.set(AUTH_SESSIONS_NAMESPACE, "no-uid-sess", {
            "expires_at": time.time() + 3600,
        })
        result = await validate_session(rt, "no-uid-sess")
        assert result is None

    @pytest.mark.asyncio
    async def test_user_not_found_returns_none(self, rt):
        """User was deleted after session was created."""
        await rt.storage.set(AUTH_SESSIONS_NAMESPACE, "orphan-sess", {
            "user_id": "deleted-user",
            "expires_at": time.time() + 3600,
        })
        result = await validate_session(rt, "orphan-sess")
        assert result is None

    @pytest.mark.asyncio
    async def test_user_not_found_session_gets_deleted(self, rt):
        await rt.storage.set(AUTH_SESSIONS_NAMESPACE, "orphan-sess2", {
            "user_id": "deleted-user2",
            "expires_at": time.time() + 3600,
        })
        await validate_session(rt, "orphan-sess2")
        remaining = await rt.storage.get(AUTH_SESSIONS_NAMESPACE, "orphan-sess2")
        assert remaining is None

    @pytest.mark.asyncio
    async def test_user_data_not_dict_returns_none(self, rt):
        await rt.storage.set(AUTH_USERS_NAMESPACE, "strange-user", "not-a-dict")
        await rt.storage.set(AUTH_SESSIONS_NAMESPACE, "strange-sess", {
            "user_id": "strange-user",
            "expires_at": time.time() + 3600,
        })
        result = await validate_session(rt, "strange-sess")
        assert result is None

    @pytest.mark.asyncio
    async def test_last_used_updated_when_old(self, rt):
        """If last_used was more than 60s ago, it gets updated."""
        await _prepare_user(rt)
        old_last_used = time.time() - 120  # 2 minutes ago
        await rt.storage.set(AUTH_SESSIONS_NAMESPACE, "lu-sess", {
            "user_id": "u1",
            "expires_at": time.time() + 3600,
            "last_used": old_last_used,
        })
        await validate_session(rt, "lu-sess")
        updated = await rt.storage.get(AUTH_SESSIONS_NAMESPACE, "lu-sess")
        assert updated["last_used"] > old_last_used

    @pytest.mark.asyncio
    async def test_last_used_not_updated_when_recent(self, rt):
        """If last_used was recent (< 60s), no storage write."""
        await _prepare_user(rt)
        recent_last_used = time.time() - 10  # 10 seconds ago
        await rt.storage.set(AUTH_SESSIONS_NAMESPACE, "recent-sess", {
            "user_id": "u1",
            "expires_at": time.time() + 3600,
            "last_used": recent_last_used,
        })
        await validate_session(rt, "recent-sess")
        updated = await rt.storage.get(AUTH_SESSIONS_NAMESPACE, "recent-sess")
        assert abs(updated["last_used"] - recent_last_used) < 1.0

    @pytest.mark.asyncio
    async def test_is_admin_propagated_from_user(self, rt):
        await _prepare_user(rt, user_id="admin-user", is_admin=True)
        await _prepare_session(rt, session_id="admin-sess", user_id="admin-user")
        ctx = await validate_session(rt, "admin-sess")
        assert ctx is not None
        assert ctx.is_admin is True

    @pytest.mark.asyncio
    async def test_revoked_session_returns_none(self, rt):
        import hashlib
        await _prepare_user(rt)
        await _prepare_session(rt)
        # Manually mark as revoked
        revoked_key = hashlib.sha256("sess1".encode()).hexdigest()
        await rt.storage.set(AUTH_REVOKED_NAMESPACE, revoked_key, {
            "revoked_at": time.time(),
            "type": "session",
        })
        result = await validate_session(rt, "sess1")
        assert result is None

    @pytest.mark.asyncio
    async def test_scopes_set_from_user_list(self, rt):
        await _prepare_user(rt, scopes=["devices.read", "devices.write"])
        await _prepare_session(rt)
        ctx = await validate_session(rt, "sess1")
        assert "devices.read" in ctx.scopes
        assert "devices.write" in ctx.scopes

    @pytest.mark.asyncio
    async def test_scopes_from_user_set(self, rt):
        await rt.storage.set(AUTH_USERS_NAMESPACE, "set-user", {
            "user_id": "set-user",
            "scopes": {"devices.*"},
            "is_admin": False,
        })
        await rt.storage.set(AUTH_SESSIONS_NAMESPACE, "set-sess", {
            "user_id": "set-user",
            "expires_at": time.time() + 3600,
            "last_used": 0,
        })
        ctx = await validate_session(rt, "set-sess")
        assert "devices.*" in ctx.scopes

    @pytest.mark.asyncio
    async def test_session_without_expires_at_is_valid(self, rt):
        """Session without expires_at should be treated as non-expiring."""
        await _prepare_user(rt)
        await rt.storage.set(AUTH_SESSIONS_NAMESPACE, "no-exp-sess", {
            "user_id": "u1",
            "last_used": time.time() - 120,
        })
        ctx = await validate_session(rt, "no-exp-sess")
        assert ctx is not None


# ---------------------------------------------------------------------------
# create_session
# ---------------------------------------------------------------------------

class TestCreateSession:

    @pytest.mark.asyncio
    async def test_create_session_returns_id(self, rt):
        await _prepare_user(rt)
        session_id = await create_session(rt, "u1")
        assert isinstance(session_id, str)
        assert len(session_id) > 16

    @pytest.mark.asyncio
    async def test_create_session_stored_in_storage(self, rt):
        await _prepare_user(rt)
        session_id = await create_session(rt, "u1")
        data = await rt.storage.get(AUTH_SESSIONS_NAMESPACE, session_id)
        assert data is not None
        assert data["user_id"] == "u1"

    @pytest.mark.asyncio
    async def test_create_session_has_expires_at(self, rt):
        await _prepare_user(rt)
        before = time.time()
        session_id = await create_session(rt, "u1")
        data = await rt.storage.get(AUTH_SESSIONS_NAMESPACE, session_id)
        assert data["expires_at"] > before

    @pytest.mark.asyncio
    async def test_create_session_user_not_found_raises(self, rt):
        with pytest.raises((ValueError, Exception)):
            await create_session(rt, "nonexistent-user")

    @pytest.mark.asyncio
    async def test_create_session_custom_expiration(self, rt):
        await _prepare_user(rt)
        before = time.time()
        session_id = await create_session(rt, "u1", expiration_seconds=7200)
        data = await rt.storage.get(AUTH_SESSIONS_NAMESPACE, session_id)
        assert data["expires_at"] >= before + 7200 - 5

    @pytest.mark.asyncio
    async def test_create_session_client_ip_stored(self, rt):
        await _prepare_user(rt)
        session_id = await create_session(rt, "u1", client_ip="192.168.1.1")
        data = await rt.storage.get(AUTH_SESSIONS_NAMESPACE, session_id)
        assert data.get("client_ip") == "192.168.1.1"
