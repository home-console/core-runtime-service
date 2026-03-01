"""
Tests for modules/api/auth/users.py (coverage: 32% → 80%+)
"""
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from modules.api.auth.users import create_user, validate_user_exists
from modules.api.auth.constants import AUTH_USERS_NAMESPACE


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
    r = SimpleNamespace(
        storage=FakeStorage(),
        service_registry=FakeServiceRegistry(),
    )
    return r


# ---------------------------------------------------------------------------
# validate_user_exists
# ---------------------------------------------------------------------------

class TestValidateUserExists:

    @pytest.mark.asyncio
    async def test_returns_false_when_not_found(self, rt):
        assert await validate_user_exists(rt, "nonexistent") is False

    @pytest.mark.asyncio
    async def test_returns_true_when_found(self, rt):
        await rt.storage.set(AUTH_USERS_NAMESPACE, "u1", {"user_id": "u1"})
        assert await validate_user_exists(rt, "u1") is True

    @pytest.mark.asyncio
    async def test_returns_false_when_value_not_dict(self, rt):
        await rt.storage.set(AUTH_USERS_NAMESPACE, "u1", "invalid-string")
        assert await validate_user_exists(rt, "u1") is False

    @pytest.mark.asyncio
    async def test_returns_false_on_storage_exception(self):
        broken = SimpleNamespace(
            storage=SimpleNamespace(get=AsyncMock(side_effect=Exception("db err")))
        )
        assert await validate_user_exists(broken, "u1") is False


# ---------------------------------------------------------------------------
# create_user
# ---------------------------------------------------------------------------

class TestCreateUser:

    @pytest.mark.asyncio
    async def test_create_user_basic(self, rt):
        await create_user(rt, "u1", ["devices.read"])
        data = await rt.storage.get(AUTH_USERS_NAMESPACE, "u1")
        assert data["user_id"] == "u1"
        assert "devices.read" in data["scopes"]
        assert data["is_admin"] is False

    @pytest.mark.asyncio
    async def test_create_user_with_username(self, rt):
        await create_user(rt, "u2", ["*"], username="alice")
        data = await rt.storage.get(AUTH_USERS_NAMESPACE, "u2")
        assert data["username"] == "alice"

    @pytest.mark.asyncio
    async def test_create_user_is_admin(self, rt):
        await create_user(rt, "admin1", ["*"], is_admin=True)
        data = await rt.storage.get(AUTH_USERS_NAMESPACE, "admin1")
        assert data["is_admin"] is True

    @pytest.mark.asyncio
    async def test_create_user_with_set_scopes(self, rt):
        await create_user(rt, "u3", {"devices.read", "devices.write"})
        data = await rt.storage.get(AUTH_USERS_NAMESPACE, "u3")
        assert "devices.read" in data["scopes"]
        assert "devices.write" in data["scopes"]

    @pytest.mark.asyncio
    async def test_create_user_invalid_scopes(self, rt):
        with pytest.raises(ValueError, match="Invalid scopes"):
            await create_user(rt, "u4", ["invalid-no-dot"])

    @pytest.mark.asyncio
    async def test_create_user_duplicate_raises(self, rt):
        await create_user(rt, "u5", ["devices.read"])
        with pytest.raises(ValueError, match="already exists"):
            await create_user(rt, "u5", ["devices.read"])

    @pytest.mark.asyncio
    async def test_create_user_with_valid_password(self, rt):
        # Use a password meeting strength requirements
        await create_user(rt, "u6", ["devices.read"], password="StrongPass123!")
        data = await rt.storage.get(AUTH_USERS_NAMESPACE, "u6")
        assert "password_hash" in data
        assert data["password_hash"] is not None

    @pytest.mark.asyncio
    async def test_create_user_with_weak_password_raises(self, rt):
        with pytest.raises(ValueError):
            await create_user(rt, "u7", ["devices.read"], password="weak")

    @pytest.mark.asyncio
    async def test_create_user_without_password_no_hash(self, rt):
        await create_user(rt, "u8", ["devices.read"])
        data = await rt.storage.get(AUTH_USERS_NAMESPACE, "u8")
        assert "password_hash" not in data

    @pytest.mark.asyncio
    async def test_create_user_has_created_at(self, rt):
        import time
        before = time.time()
        await create_user(rt, "u9", ["devices.read"])
        data = await rt.storage.get(AUTH_USERS_NAMESPACE, "u9")
        assert data["created_at"] >= before

    @pytest.mark.asyncio
    async def test_create_user_default_username_equals_user_id(self, rt):
        await create_user(rt, "my-user", ["devices.read"])
        data = await rt.storage.get(AUTH_USERS_NAMESPACE, "my-user")
        assert data["username"] == "my-user"

    @pytest.mark.asyncio
    async def test_create_user_wildcard_scope(self, rt):
        # "*" is a valid scope
        await create_user(rt, "u10", ["*"])
        data = await rt.storage.get(AUTH_USERS_NAMESPACE, "u10")
        assert "*" in data["scopes"]

    @pytest.mark.asyncio
    async def test_create_user_wildcard_namespace_scope(self, rt):
        await create_user(rt, "u11", ["devices.*"])
        data = await rt.storage.get(AUTH_USERS_NAMESPACE, "u11")
        assert "devices.*" in data["scopes"]
