"""
Тесты для Authorization Policy Layer — Phase 4 (декларативная auth).

ACTION_SCOPE_MAP удалён. Все проверки идут через:
- endpoint_auth_config.required_scopes (EndpointAuthConfig)
- svc_auth.required_scopes (ServiceAuthConfig из service_registry)
- admin.* fallback для admin.* действий
- wildcard "*" даёт доступ ко всему

Проверяют:
- check() возвращает True/False
- require() бросает AuthorizationError
- Wildcard scopes работают
- Admin доступ работает
- Декларативная auth через endpoint_auth_config
"""

import pytest
from modules.api.auth import RequestContext
from core.http.models import EndpointAuthConfig
from modules.api.authz import (
    check,
    require,
    AuthorizationError,
    get_required_scope,
    get_required_scopes,
)


class TestCheck:
    """Тесты для check()."""

    def test_check_no_context(self):
        """Тест: нет контекста → False."""
        assert check(None, "devices.list") is False
        # Public endpoint разрешён даже без контекста
        assert check(None, "devices.list", endpoint_auth_config=EndpointAuthConfig(public=True)) is True

    def test_check_admin_full_access(self):
        """Тест: admin имеет полный доступ."""
        ctx = RequestContext(
            subject="admin",
            scopes=[],
            is_admin=True,
            source="api_key"
        )

        assert check(ctx, "devices.list") is True
        assert check(ctx, "devices.set_state") is True
        assert check(ctx, "admin.v1.runtime") is True
        assert check(ctx, "unknown.action") is True

    def test_check_admin_action_requires_admin(self):
        """Тест: admin действия требуют admin прав."""
        ctx = RequestContext(
            subject="user:user_123",
            scopes=["devices.read"],
            is_admin=False,
            source="session"
        )

        assert check(ctx, "admin.v1.runtime") is False
        assert check(ctx, "admin.list_plugins") is False

    def test_check_admin_action_with_admin_scope(self):
        """Тест: admin действия разрешены с admin.* scope."""
        ctx = RequestContext(
            subject="user:user_123",
            scopes=["admin.*"],
            is_admin=False,
            source="session"
        )

        assert check(ctx, "admin.v1.runtime") is True
        assert check(ctx, "admin.list_plugins") is True

    def test_check_endpoint_auth_required_scopes(self):
        """Тест: endpoint_auth_config.required_scopes — точное совпадение."""
        ctx = RequestContext(
            subject="user:user_123",
            scopes=["devices.read", "devices.write"],
            is_admin=False,
            source="session"
        )
        ep_auth_read = EndpointAuthConfig(required_scopes=["devices.read"])
        ep_auth_write = EndpointAuthConfig(required_scopes=["devices.write"])

        assert check(ctx, "devices.list", endpoint_auth_config=ep_auth_read) is True
        assert check(ctx, "devices.set_state", endpoint_auth_config=ep_auth_write) is True

        # Нет нужного scope → False
        assert check(ctx, "automation.trigger", endpoint_auth_config=EndpointAuthConfig(required_scopes=["automation.write"])) is False

    def test_check_endpoint_auth_public(self):
        """Тест: endpoint_auth_config.public=True → всегда True."""
        ctx = RequestContext(
            subject="user:user_123",
            scopes=[],
            is_admin=False,
            source="session"
        )
        ep_public = EndpointAuthConfig(public=True)
        assert check(ctx, "devices.list", endpoint_auth_config=ep_public) is True
        assert check(None, "devices.list", endpoint_auth_config=ep_public) is True

    def test_check_namespace_wildcard(self):
        """Тест: wildcard для namespace — работает с endpoint_auth_config."""
        ctx = RequestContext(
            subject="user:user_123",
            scopes=["devices.*"],
            is_admin=False,
            source="session"
        )
        ep_auth = EndpointAuthConfig(required_scopes=["devices.read"])

        assert check(ctx, "devices.list", endpoint_auth_config=ep_auth) is True
        assert check(ctx, "devices.get", endpoint_auth_config=ep_auth) is True
        # Без endpoint_auth_config → fail-closed
        assert check(ctx, "devices.list") is False

    def test_check_full_wildcard(self):
        """Тест: полный wildcard (*)."""
        ctx = RequestContext(
            subject="user:user_123",
            scopes=["*"],
            is_admin=False,
            source="session"
        )

        assert check(ctx, "devices.list") is True
        assert check(ctx, "automation.trigger") is True
        assert check(ctx, "presence.set") is True
        # Даже без endpoint_auth_config
        assert check(ctx, "devices.list", endpoint_auth_config=EndpointAuthConfig(required_scopes=["devices.read"])) is True

    def test_check_action_not_in_mapping(self):
        """Тест: action не найден → fail-closed (если нет *)."""
        ctx = RequestContext(
            subject="user:user_123",
            scopes=["devices.read"],
            is_admin=False,
            source="session"
        )

        # Без endpoint_auth_config и без * → fail-closed
        assert check(ctx, "unknown.action") is False

        # С * должно быть True для любого action
        ctx_with_wildcard = RequestContext(
            subject="user:user_123",
            scopes=["*"],
            is_admin=False,
            source="session"
        )
        assert check(ctx_with_wildcard, "unknown.action") is True

    def test_check_resource_parameter_ignored(self):
        """Тест: resource параметр принимается, но для ownership/shared_with проверок."""
        ctx = RequestContext(
            subject="user:user_123",
            scopes=["devices.read"],
            is_admin=False,
            source="session",
            user_id="user:user_123",
        )
        ep_auth = EndpointAuthConfig(required_scopes=["devices.read"])

        # resource с owner_id = ctx.user_id → разрешено
        assert check(ctx, "devices.list", {"owner_id": "user:user_123"}, endpoint_auth_config=ep_auth) is True
        # Без owner/shared → проверяем только действие
        assert check(ctx, "devices.list", None, endpoint_auth_config=ep_auth) is True
        assert check(ctx, "devices.list", {}, endpoint_auth_config=ep_auth) is True


class TestRequire:
    """Тесты для require()."""

    def test_require_success(self):
        """Тест: require() не бросает при успехе."""
        ctx = RequestContext(
            subject="user:user_123",
            scopes=["devices.read"],
            is_admin=False,
            source="session"
        )
        ep_auth = EndpointAuthConfig(required_scopes=["devices.read"])

        require(ctx, "devices.list", endpoint_auth_config=ep_auth)
        require(ctx, "devices.get", endpoint_auth_config=ep_auth)

    def test_require_raises_on_failure(self):
        """Тест: require() бросает AuthorizationError при отказе."""
        ctx = RequestContext(
            subject="user:user_123",
            scopes=["devices.read"],
            is_admin=False,
            source="session"
        )
        ep_auth_write = EndpointAuthConfig(required_scopes=["devices.write"])

        with pytest.raises(AuthorizationError, match="Authorization failed"):
            require(ctx, "devices.set_state", endpoint_auth_config=ep_auth_write)

    def test_require_no_context_raises(self):
        """Тест: require() бросает при отсутствии контекста."""
        with pytest.raises(AuthorizationError):
            require(None, "devices.list")

    def test_require_admin_action_without_admin_raises(self):
        """Тест: require() бросает для admin действий без admin прав."""
        ctx = RequestContext(
            subject="user:user_123",
            scopes=["devices.read"],
            is_admin=False,
            source="session"
        )

        with pytest.raises(AuthorizationError):
            require(ctx, "admin.v1.runtime")


class TestGetRequiredScope:
    """Тесты для get_required_scope() — DEPRECATED, но работает."""

    def test_get_required_scope_admin(self):
        """Тест: возвращает admin.* для admin действий."""
        assert get_required_scope("admin.v1.runtime") == "admin.*"
        assert get_required_scope("admin.list_plugins") == "admin.*"

    def test_get_required_scope_not_found(self):
        """Тест: возвращает None для не найденного action (ACTION_SCOPE_MAP удалён)."""
        assert get_required_scope("unknown.action") is None


class TestGetRequiredScopes:
    """Тесты для get_required_scopes() — новая функция."""

    def test_from_endpoint_auth_config(self):
        """Тест: возвращает scopes из endpoint_auth_config."""
        ep_auth = EndpointAuthConfig(required_scopes=["devices.read"])
        assert get_required_scopes("devices.list", endpoint_auth_config=ep_auth) == ["devices.read"]

    def test_admin_fallback(self):
        """Тест: admin.* actions возвращают ["admin.*"] без endpoint_auth_config."""
        assert get_required_scopes("admin.v1.runtime") == ["admin.*"]

    def test_non_admin_no_config_returns_empty(self):
        """Тест: non-admin без endpoint_auth_config → пусто."""
        assert get_required_scopes("unknown.action") == []

    def test_public_returns_empty(self):
        """Тест: public endpoint → пусто scopes (public — отдельный флаг)."""
        ep_public = EndpointAuthConfig(public=True)
        assert get_required_scopes("devices.list", endpoint_auth_config=ep_public) == []


class TestWildcardScopes:
    """Тесты для wildcard scopes."""

    def test_namespace_wildcard_read(self):
        """Тест: devices.* даёт доступ к read и write с endpoint_auth_config."""
        ctx = RequestContext(
            subject="user:user_123",
            scopes=["devices.*"],
            is_admin=False,
            source="session"
        )
        ep_auth = EndpointAuthConfig(required_scopes=["devices.read"])

        assert check(ctx, "devices.list", endpoint_auth_config=ep_auth) is True
        assert check(ctx, "devices.get", endpoint_auth_config=ep_auth) is True
        # Без endpoint_auth_config → fail-closed
        assert check(ctx, "devices.list") is False

    def test_namespace_wildcard_automation(self):
        """Тест: automation.* даёт доступ к automation действиям с endpoint_auth_config."""
        ctx = RequestContext(
            subject="user:user_123",
            scopes=["automation.*"],
            is_admin=False,
            source="session"
        )
        ep_auth_list = EndpointAuthConfig(required_scopes=["automation.read"])
        ep_auth_trigger = EndpointAuthConfig(required_scopes=["automation.write"])

        assert check(ctx, "automation.list", endpoint_auth_config=ep_auth_list) is True
        assert check(ctx, "automation.trigger", endpoint_auth_config=ep_auth_trigger) is True
        # Без endpoint_auth_config → fail-closed
        assert check(ctx, "automation.list") is False
        # devices.list требует devices.read, но automation.* ≠ devices.* → fail-closed
        assert check(ctx, "devices.list", endpoint_auth_config=EndpointAuthConfig(required_scopes=["devices.read"])) is False

    def test_full_wildcard_all_actions(self):
        """Тест: * даёт доступ ко всем действиям."""
        ctx = RequestContext(
            subject="user:user_123",
            scopes=["*"],
            is_admin=False,
            source="session"
        )

        assert check(ctx, "devices.list") is True
        assert check(ctx, "automation.trigger") is True
        assert check(ctx, "presence.set") is True
        assert check(ctx, "admin.v1.runtime") is True  # * даёт доступ даже к admin
