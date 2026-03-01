"""
Targeted tests for coverage gaps identified in the 79% run.
Covers: utils.py lines 32,64 | revocation.py lines 38-39,58-59,82-83,102-103,126-127,146-147
"""
import pytest
import hashlib
from types import SimpleNamespace

from modules.api.auth.utils import validate_scopes, check_service_scope
from modules.api.auth.revocation import revoke_api_key, revoke_session, revoke_refresh_token, is_revoked
from modules.api.auth.constants import AUTH_REVOKED_NAMESPACE


# ---------------------------------------------------------------------------
# utils.py line 32 — scope with leading/trailing dot
# ---------------------------------------------------------------------------

class TestValidateScopesEdgeCases:

    def test_scope_with_trailing_dot_returns_false(self):
        assert validate_scopes(["devices."]) is False

    def test_scope_with_leading_dot_returns_false(self):
        assert validate_scopes([".devices"]) is False

    def test_scope_with_both_dots_but_leading_one_returns_false(self):
        assert validate_scopes([".devices.read"]) is False


# ---------------------------------------------------------------------------
# utils.py line 64 — service_name without dot for non-admin non-covered path
# ---------------------------------------------------------------------------

class TestCheckServiceScopeNoDot:

    def test_service_name_without_dot_returns_false(self):
        """service_name with no dot and non-admin context → False (line 64)."""
        ctx = SimpleNamespace(scopes={"*"}, is_admin=False, source="jwt")
        assert check_service_scope(ctx, "nodot") is False

    def test_service_name_empty_returns_false(self):
        ctx = SimpleNamespace(scopes={"*"}, is_admin=False, source="jwt")
        assert check_service_scope(ctx, "") is False


# ---------------------------------------------------------------------------
# revocation.py — storage.delete raises (lines 38-39 pattern + lines 58-59)
# ---------------------------------------------------------------------------

class RaisingDeleteStorage:
    """Storage where delete() always raises, set() works normally."""
    def __init__(self):
        self._d = {}

    async def get(self, ns, key):
        return self._d.get(ns, {}).get(key)

    async def set(self, ns, key, value):
        self._d.setdefault(ns, {})[key] = value

    async def delete(self, ns, key):
        raise Exception("delete error")


class RaisingServiceRegistry:
    """ServiceRegistry that raises on call() — to cover inner except in outer except."""
    async def call(self, *args, **kwargs):
        raise Exception("service_registry error")


class RaisingSetStorage:
    """Storage that raises on set() to trigger outer except."""
    async def get(self, ns, key):
        return None

    async def set(self, ns, key, value):
        raise Exception("set error")

    async def delete(self, ns, key):
        pass


class FakeSvcRegistry:
    async def call(self, *args, **kwargs):
        return None


@pytest.fixture
def rt_del_raises():
    return SimpleNamespace(
        storage=RaisingDeleteStorage(),
        service_registry=FakeSvcRegistry(),
    )


@pytest.fixture
def rt_svc_raises():
    """storage.set raises → outer except triggers → service_registry also raises → inner except."""
    return SimpleNamespace(
        storage=RaisingSetStorage(),
        service_registry=RaisingServiceRegistry(),
    )


class TestRevocationDeleteRaises:
    """Cover lines 38-39 (delete fails) in revoke_* functions."""

    @pytest.mark.asyncio
    async def test_revoke_api_key_delete_raises_no_crash(self, rt_del_raises):
        await revoke_api_key(rt_del_raises, "key-for-del-test")

    @pytest.mark.asyncio
    async def test_revoke_session_delete_raises_no_crash(self, rt_del_raises):
        await revoke_session(rt_del_raises, "session-for-del-test")

    @pytest.mark.asyncio
    async def test_revoke_refresh_token_delete_raises_no_crash(self, rt_del_raises):
        await revoke_refresh_token(rt_del_raises, "token-for-del-test")


class TestRevocationServiceRegistryAlsoRaises:
    """Cover lines 58-59 pattern (service_registry.call also raises in except block)."""

    @pytest.mark.asyncio
    async def test_revoke_api_key_svc_raises_no_crash(self, rt_svc_raises):
        await revoke_api_key(rt_svc_raises, "key-2")

    @pytest.mark.asyncio
    async def test_revoke_session_svc_raises_no_crash(self, rt_svc_raises):
        await revoke_session(rt_svc_raises, "session-2")

    @pytest.mark.asyncio
    async def test_revoke_refresh_token_svc_raises_no_crash(self, rt_svc_raises):
        await revoke_refresh_token(rt_svc_raises, "token-2")


class TestIsRevokedStorageRaises:
    """Cover is_revoked exception path (lines 179-181 equivalent)."""

    @pytest.mark.asyncio
    async def test_is_revoked_with_raising_storage(self):
        rt = SimpleNamespace(
            storage=RaisingSetStorage(),  # get also raises
            service_registry=SimpleNamespace(call=lambda *a, **kw: None),
        )
        # is_revoked does storage.get which doesn't raise in RaisingSetStorage
        # Need a storage where get raises
        class GetRaises:
            async def get(self, *a, **kw):
                raise Exception("get error")
        rt2 = SimpleNamespace(storage=GetRaises())
        result = await is_revoked(rt2, "any-id", "api_key")
        assert result is False

    @pytest.mark.asyncio
    async def test_is_revoked_entry_with_none_type(self):
        storage = RaisingDeleteStorage()  # normal get/set
        await storage.set(AUTH_REVOKED_NAMESPACE, hashlib.sha256(b"k").hexdigest(), {"revoked_at": 1.0})
        rt = SimpleNamespace(storage=storage)
        # No 'type' key → type check fails → False
        result = await is_revoked(rt, "k", "api_key")
        assert result is False
