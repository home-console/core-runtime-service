"""
Тесты для Authorization Policy Layer.

Проверяют:
- check() возвращает True/False
- require() бросает AuthorizationError
- Wildcard scopes работают
- Admin доступ работает
"""

import pytest
from modules.api.auth import RequestContext
from modules.api.authz import (
    check,
    require,
    AuthorizationError,
    get_required_scope,
)


class TestCheck:
    """Тесты для check()."""
    
    def test_check_no_context(self):
        """Тест: нет контекста → False."""
        assert check(None, "devices.list") is False
    
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
    
    def test_check_exact_scope_match(self):
        """Тест: точное совпадение scope."""
        ctx = RequestContext(
            subject="user:user_123",
            scopes=["devices.read", "devices.write"],
            is_admin=False,
            source="session"
        )
        
        assert check(ctx, "devices.list") is True
        assert check(ctx, "devices.get") is True
        assert check(ctx, "devices.set_state") is True
        assert check(ctx, "automation.trigger") is False
    
    def test_check_namespace_wildcard(self):
        """Тест: wildcard для namespace."""
        ctx = RequestContext(
            subject="user:user_123",
            scopes=["devices.*"],
            is_admin=False,
            source="session"
        )
        
        assert check(ctx, "devices.list") is True
        assert check(ctx, "devices.get") is True
        assert check(ctx, "devices.set_state") is True
        assert check(ctx, "automation.trigger") is False
    
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
    
    def test_check_action_not_in_mapping(self):
        """Тест: action не найден в mapping → False (если нет *)."""
        ctx = RequestContext(
            subject="user:user_123",
            scopes=["devices.read"],
            is_admin=False,
            source="session"
        )
        
        # Без * и без mapping → False
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
        """Тест: resource параметр принимается, но не используется."""
        ctx = RequestContext(
            subject="user:user_123",
            scopes=["devices.read"],
            is_admin=False,
            source="session"
        )
        
        # resource передаётся, но не влияет на результат
        assert check(ctx, "devices.list", {"device_id": "123"}) is True
        assert check(ctx, "devices.list", None) is True
        assert check(ctx, "devices.list", {}) is True


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
        
        # Не должно бросать исключение
        require(ctx, "devices.list")
        require(ctx, "devices.get")
    
    def test_require_raises_on_failure(self):
        """Тест: require() бросает AuthorizationError при отказе."""
        ctx = RequestContext(
            subject="user:user_123",
            scopes=["devices.read"],
            is_admin=False,
            source="session"
        )
        
        with pytest.raises(AuthorizationError, match="Authorization failed"):
            require(ctx, "devices.set_state")  # Нет devices.write
    
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
    """Тесты для get_required_scope()."""
    
    def test_get_required_scope_found(self):
        """Тест: возвращает scope для найденного action."""
        assert get_required_scope("devices.list") == "devices.read"
        assert get_required_scope("devices.set_state") == "devices.write"
        assert get_required_scope("automation.trigger") == "automation.write"
    
    def test_get_required_scope_admin(self):
        """Тест: возвращает admin.* для admin действий."""
        assert get_required_scope("admin.v1.runtime") == "admin.*"
        assert get_required_scope("admin.list_plugins") == "admin.*"
    
    def test_get_required_scope_not_found(self):
        """Тест: возвращает None для не найденного action."""
        assert get_required_scope("unknown.action") is None


class TestWildcardScopes:
    """Тесты для wildcard scopes."""
    
    def test_namespace_wildcard_read(self):
        """Тест: devices.* даёт доступ к read и write."""
        ctx = RequestContext(
            subject="user:user_123",
            scopes=["devices.*"],
            is_admin=False,
            source="session"
        )
        
        assert check(ctx, "devices.list") is True
        assert check(ctx, "devices.get") is True
        assert check(ctx, "devices.set_state") is True
    
    def test_namespace_wildcard_automation(self):
        """Тест: automation.* даёт доступ ко всем automation действиям."""
        ctx = RequestContext(
            subject="user:user_123",
            scopes=["automation.*"],
            is_admin=False,
            source="session"
        )
        
        assert check(ctx, "automation.list") is True
        assert check(ctx, "automation.trigger") is True
        assert check(ctx, "devices.list") is False
    
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
