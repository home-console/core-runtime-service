"""
Tests for modules/api/auth/utils.py (coverage: 33% → 80%+)
"""
import pytest
from types import SimpleNamespace

from modules.api.auth.utils import validate_scopes, check_service_scope


# ---------------------------------------------------------------------------
# validate_scopes
# ---------------------------------------------------------------------------

class TestValidateScopes:

    def test_valid_list_returns_true(self):
        assert validate_scopes(["devices.read", "devices.write"]) is True

    def test_valid_set_returns_true(self):
        assert validate_scopes({"devices.read", "agents.list"}) is True

    def test_empty_list_returns_true(self):
        assert validate_scopes([]) is True

    def test_empty_set_returns_true(self):
        assert validate_scopes(set()) is True

    def test_not_list_or_set_returns_false(self):
        assert validate_scopes("devices.read") is False

    def test_dict_returns_false(self):
        assert validate_scopes({"scope": "devices.read"}) is False

    def test_tuple_returns_false(self):
        assert validate_scopes(("devices.read",)) is False

    def test_non_string_item_returns_false(self):
        assert validate_scopes([123]) is False

    def test_none_item_returns_false(self):
        assert validate_scopes([None]) is False

    def test_no_dot_returns_false(self):
        assert validate_scopes(["nodereturn"]) is False

    def test_wildcard_star_returns_true(self):
        assert validate_scopes(["*"]) is True

    def test_namespace_wildcard_returns_true(self):
        assert validate_scopes(["devices.*"]) is True

    def test_full_scope_valid(self):
        assert validate_scopes(["admin.users.read"]) is True

    def test_mixed_valid_and_invalid_returns_false(self):
        assert validate_scopes(["devices.read", "invalid"]) is False

    def test_multiple_scopes_all_valid(self):
        assert validate_scopes(["devices.read", "devices.write", "admin.status.get"]) is True


# ---------------------------------------------------------------------------
# check_service_scope
# ---------------------------------------------------------------------------

class TestCheckServiceScope:

    def _ctx(self, scopes=None, is_admin=False, source="jwt"):
        return SimpleNamespace(
            scopes=set(scopes or []),
            is_admin=is_admin,
            source=source,
        )

    def test_none_context_returns_false(self):
        assert check_service_scope(None, "devices.read") is False

    def test_admin_user_can_access_anything(self):
        ctx = self._ctx(is_admin=True)
        assert check_service_scope(ctx, "devices.read") is True

    def test_admin_user_can_access_admin_scope(self):
        ctx = self._ctx(is_admin=True)
        assert check_service_scope(ctx, "admin.users.create") is True

    def test_non_admin_cannot_access_admin_scope(self):
        ctx = self._ctx(scopes=["devices.read"], is_admin=False)
        assert check_service_scope(ctx, "admin.users.create") is False

    def test_exact_scope_match(self):
        ctx = self._ctx(scopes=["devices.read"])
        assert check_service_scope(ctx, "devices.read") is True

    def test_exact_scope_no_match(self):
        ctx = self._ctx(scopes=["devices.read"])
        assert check_service_scope(ctx, "devices.write") is False

    def test_namespace_wildcard_match(self):
        ctx = self._ctx(scopes=["devices.*"])
        assert check_service_scope(ctx, "devices.read") is True

    def test_namespace_wildcard_no_match_other_ns(self):
        ctx = self._ctx(scopes=["devices.*"])
        assert check_service_scope(ctx, "agents.list") is False

    def test_global_wildcard_matches_anything(self):
        ctx = self._ctx(scopes=["*"])
        assert check_service_scope(ctx, "devices.read") is True

    def test_global_wildcard_does_not_match_admin_for_non_admin(self):
        """Non-admin with '*' still cannot access admin.* services."""
        ctx = self._ctx(scopes=["*"])
        assert check_service_scope(ctx, "admin.users.delete") is False

    def test_empty_scopes_returns_false(self):
        ctx = self._ctx(scopes=[])
        assert check_service_scope(ctx, "devices.read") is False

    def test_multiple_scopes_first_matches(self):
        ctx = self._ctx(scopes=["devices.read", "agents.list"])
        assert check_service_scope(ctx, "devices.read") is True

    def test_multiple_scopes_second_matches(self):
        ctx = self._ctx(scopes=["devices.read", "agents.list"])
        assert check_service_scope(ctx, "agents.list") is True

    def test_multiple_scopes_none_match(self):
        ctx = self._ctx(scopes=["devices.read", "agents.list"])
        assert check_service_scope(ctx, "admin.users.get") is False
