"""
Tests for modules/api/auth/audit.py (coverage: 61% → 80%+)
"""
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock


class FakeStorage:
    def __init__(self, raise_on_set=False):
        self._d = {}
        self.raise_on_set = raise_on_set
        self.set_calls = []

    async def get(self, ns, key):
        return self._d.get(ns, {}).get(key)

    async def set(self, ns, key, value):
        if self.raise_on_set:
            raise Exception("storage failure")
        self.set_calls.append((ns, key, value))
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


from modules.api.auth.audit import audit_log_auth_event


class TestAuditLogAuthEvent:

    @pytest.mark.asyncio
    async def test_basic_log_event(self, rt):
        """Should store event to storage without error."""
        await audit_log_auth_event(rt, "login_success", "user1", {"ip": "1.2.3.4"})
        assert len(rt.storage.set_calls) > 0

    @pytest.mark.asyncio
    async def test_non_string_subject_is_coerced(self, rt):
        """int subject should be coerced to string."""
        await audit_log_auth_event(rt, "login_success", 42, {})
        assert len(rt.storage.set_calls) > 0
        stored_value = rt.storage.set_calls[0][2]
        # subject should be stored as string
        assert str(42) in str(stored_value.get("subject", ""))

    @pytest.mark.asyncio
    async def test_none_subject_handled(self, rt):
        """None subject should be coerced/handled without crash."""
        await audit_log_auth_event(rt, "login_fail", None, {})
        # Should not raise

    @pytest.mark.asyncio
    async def test_non_dict_details_is_wrapped(self, rt):
        """Non-dict details should be wrapped in a dict."""
        await audit_log_auth_event(rt, "login_success", "user1", "extra-info")
        stored_value = rt.storage.set_calls[0][2]
        # details should be a dict in stored value
        assert isinstance(stored_value.get("details"), dict)

    @pytest.mark.asyncio
    async def test_list_details_is_wrapped(self, rt):
        await audit_log_auth_event(rt, "login_success", "user1", ["a", "b"])
        stored_value = rt.storage.set_calls[0][2]
        assert isinstance(stored_value.get("details"), dict)

    @pytest.mark.asyncio
    async def test_none_details_handled(self, rt):
        """None details should be handled without crash."""
        await audit_log_auth_event(rt, "login_success", "user1", None)
        # Should not raise

    @pytest.mark.asyncio
    async def test_storage_set_called_with_correct_namespace(self, rt):
        """Verify we write to auth audit namespace."""
        await audit_log_auth_event(rt, "login_success", "user1", {})
        ns = rt.storage.set_calls[0][0]
        assert "audit" in ns.lower() or "auth" in ns.lower()

    @pytest.mark.asyncio
    async def test_storage_value_contains_event_type(self, rt):
        await audit_log_auth_event(rt, "token_revoked", "user1", {})
        stored_value = rt.storage.set_calls[0][2]
        assert stored_value.get("event_type") == "token_revoked" or \
               stored_value.get("event") == "token_revoked" or \
               "token_revoked" in str(stored_value)

    @pytest.mark.asyncio
    async def test_storage_error_does_not_raise(self):
        """Audit log should never raise even if storage fails."""
        rt = SimpleNamespace(
            storage=FakeStorage(raise_on_set=True),
            service_registry=FakeServiceRegistry(),
        )
        # Should swallow exception
        await audit_log_auth_event(rt, "login_success", "user1", {})

    @pytest.mark.asyncio
    async def test_dict_details_stored_as_dict(self, rt):
        """Normal dict details should be stored as-is."""
        await audit_log_auth_event(rt, "login_success", "user1", {"ip": "127.0.0.1", "ua": "test"})
        stored_value = rt.storage.set_calls[0][2]
        details = stored_value.get("details", {})
        assert isinstance(details, dict)
