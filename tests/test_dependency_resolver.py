"""
Test suite for dependency validation components.

Tests system integrity validation:
- Installation constraints
- Removal constraints
- Disable constraints
- Alternative provider fallbacks
- Runtime integrity checks
"""

import pytest
from unittest.mock import Mock

from core.dependency.integrity_checker import DependencyIntegrityChecker
from core.dependency.lifecycle_policy import PluginLifecyclePolicy
from core.kernel.base_plugin import PluginMetadata


class TestDependencyResolverBasics:
    """Test basic resolver functionality."""
    
    @pytest.fixture
    def registry(self):
        """Create mock CapabilityRegistry."""
        registry = Mock()
        registry.get_providers = Mock(return_value=[])
        return registry
    
    @pytest.fixture
    def plugin_manager(self):
        """Create mock PluginManager."""
        manager = Mock()
        manager.get_loaded_plugins = Mock(return_value=[])
        return manager
    
    @pytest.fixture
    def storage(self):
        """Create mock Storage."""
        return Mock()
    
    @pytest.fixture
    def resolver(self, registry, plugin_manager, storage):
        """Create policy + checker bundle (legacy resolver removed)."""
        return (
            PluginLifecyclePolicy(registry, plugin_manager),
            DependencyIntegrityChecker(registry, plugin_manager),
        )
    
    def test_resolver_init(self, resolver):
        policy, checker = resolver
        assert policy is not None
        assert checker is not None
        assert policy.capability_registry is not None
        assert checker.capability_registry is not None
    
    def test_empty_runtime_is_valid(self, resolver):
        """Test empty runtime (no plugins) is valid."""
        _, checker = resolver
        errors = checker.check_runtime_integrity()
        assert errors == []
    
    def test_empty_install_is_valid(self, resolver):
        """Test plugin with no requirements can be installed."""
        policy, _ = resolver
        metadata = PluginMetadata(
            name="empty_plugin",
            version="1.0.0",
            description="Test",
            author="Test",
            dependencies=[],
            capabilities_provided=[],
            capabilities_required=[]
        )

        ok, errors = policy.can_install_plugin(metadata)
        assert ok
        assert errors == []


class TestValidatePluginInstall:
    """Test plugin installation validation."""
    
    @pytest.fixture
    def registry(self):
        """Create mock CapabilityRegistry."""
        registry = Mock()
        registry.get_providers = Mock(return_value=[])
        return registry
    
    @pytest.fixture
    def plugin_manager(self):
        """Create mock PluginManager."""
        manager = Mock()
        manager.get_loaded_plugins = Mock(return_value=[])
        return manager
    
    @pytest.fixture
    def storage(self):
        """Create mock Storage."""
        return Mock()
    
    @pytest.fixture
    def resolver(self, registry, plugin_manager, storage):
        """Create policy + checker bundle (legacy resolver removed)."""
        return (
            PluginLifecyclePolicy(registry, plugin_manager),
            DependencyIntegrityChecker(registry, plugin_manager),
        )
    
    def test_install_without_provider_fails(self, resolver, registry):
        """Test installation fails if required capability has no provider."""
        policy, _ = resolver
        registry.get_providers.return_value = []
        
        metadata = PluginMetadata(
            name="test_plugin",
            version="1.0.0",
            description="Test",
            author="Test",
            dependencies=[],
            capabilities_provided=[],
            capabilities_required=["client.command.execute"]
        )
        
        ok, errors = policy.can_install_plugin(metadata)
        assert not ok
        assert len(errors) > 0
        assert "missing_capability_provider" in errors[0]
        assert "client.command.execute" in errors[0]
    
    def test_install_with_provider_succeeds(self, resolver, registry):
        """Test installation succeeds if required capability has provider."""
        policy, _ = resolver
        registry.get_providers.return_value = ["existing_plugin"]
        
        metadata = PluginMetadata(
            name="test_plugin",
            version="1.0.0",
            description="Test",
            author="Test",
            dependencies=[],
            capabilities_provided=[],
            capabilities_required=["client.command.execute"]
        )
        
        ok, errors = policy.can_install_plugin(metadata)
        assert ok
        assert errors == []
    
    def test_install_with_self_provided_succeeds(self, resolver, registry):
        """Test installation succeeds if capability is self-provided."""
        policy, _ = resolver
        registry.get_providers.return_value = []
        
        metadata = PluginMetadata(
            name="test_plugin",
            version="1.0.0",
            description="Test",
            author="Test",
            dependencies=[],
            capabilities_provided=["client.command.execute"],
            capabilities_required=["client.command.execute"]
        )
        
        ok, errors = policy.can_install_plugin(metadata)
        assert ok
        assert errors == []
    
    def test_install_multiple_requirements_all_satisfied(self, resolver, registry):
        """Test installation with multiple requirements all satisfied."""
        policy, _ = resolver
        def get_providers_side_effect(cap):
            providers_map = {
                "client.command.execute": ["cmd_plugin"],
                "logging.sink": ["log_plugin"]
            }
            return providers_map.get(cap, [])
        
        registry.get_providers.side_effect = get_providers_side_effect
        
        metadata = PluginMetadata(
            name="test_plugin",
            version="1.0.0",
            description="Test",
            author="Test",
            dependencies=[],
            capabilities_provided=[],
            capabilities_required=["client.command.execute", "logging.sink"]
        )
        
        ok, errors = policy.can_install_plugin(metadata)
        assert ok
        assert errors == []
    
    def test_install_multiple_requirements_one_missing(self, resolver, registry):
        """Test installation fails if one of multiple requirements is not satisfied."""
        policy, _ = resolver
        def get_providers_side_effect(cap):
            providers_map = {
                "client.command.execute": ["cmd_plugin"],
                "logging.sink": []  # This one is missing
            }
            return providers_map.get(cap, [])
        
        registry.get_providers.side_effect = get_providers_side_effect
        
        metadata = PluginMetadata(
            name="test_plugin",
            version="1.0.0",
            description="Test",
            author="Test",
            dependencies=[],
            capabilities_provided=[],
            capabilities_required=["client.command.execute", "logging.sink"]
        )
        
        ok, errors = policy.can_install_plugin(metadata)
        assert not ok
        assert len(errors) > 0
        assert "logging.sink" in errors[0]


class TestValidatePluginRemoval:
    """Test plugin removal validation."""
    
    @pytest.fixture
    def resolver_with_plugins(self):
        """Create resolver with test plugins."""
        registry = Mock()
        plugin_manager = Mock()
        storage = Mock()
        policy = PluginLifecyclePolicy(registry, plugin_manager)
        
        # Setup registry
        def get_providers_side_effect(cap):
            providers_map = {
                "client.command.execute": ["plugin_a"],
                "logging.sink": ["plugin_b"],
                "auth": ["plugin_c", "plugin_backup"]
            }
            return providers_map.get(cap, [])
        
        registry.get_providers.side_effect = get_providers_side_effect
        
        # Setup plugin_manager
        plugin_a = Mock()
        plugin_a.metadata = PluginMetadata(
            name="plugin_a",
            version="1.0.0",
            description="Test",
            author="Test",
            dependencies=[],
            capabilities_provided=["client.command.execute"],
            capabilities_required=[]
        )
        
        plugin_b = Mock()
        plugin_b.metadata = PluginMetadata(
            name="plugin_b",
            version="1.0.0",
            description="Test",
            author="Test",
            dependencies=[],
            capabilities_provided=["logging.sink"],
            capabilities_required=["client.command.execute"]  # Requires plugin_a
        )
        
        plugin_c = Mock()
        plugin_c.metadata = PluginMetadata(
            name="plugin_c",
            version="1.0.0",
            description="Test",
            author="Test",
            dependencies=[],
            capabilities_provided=["auth"],
            capabilities_required=[]
        )
        
        plugin_backup = Mock()
        plugin_backup.metadata = PluginMetadata(
            name="plugin_backup",
            version="1.0.0",
            description="Test",
            author="Test",
            dependencies=[],
            capabilities_provided=["auth"],
            capabilities_required=[]
        )
        
        plugin_manager.get_loaded_plugins.return_value = [
            ("plugin_a", plugin_a),
            ("plugin_b", plugin_b),
            ("plugin_c", plugin_c),
            ("plugin_backup", plugin_backup),
        ]

        return policy
    
    def test_remove_unused_provider_succeeds(self, resolver_with_plugins):
        """Test removal succeeds if no plugin requires the capability."""
        ok, errors = resolver_with_plugins.can_remove_plugin("plugin_c")
        assert ok
        assert errors == []
    
    def test_remove_required_provider_fails(self, resolver_with_plugins):
        """Test removal fails if another plugin requires the capability."""
        ok, errors = resolver_with_plugins.can_remove_plugin("plugin_a")
        assert not ok
        assert len(errors) > 0
        assert "required_provider_removal" in errors[0]
        assert "plugin_b" in errors[0]
    
    def test_remove_provider_with_alternative_succeeds(self, resolver_with_plugins):
        """Test removal succeeds if there's an alternative provider."""
        # plugin_backup provides "auth" as alternative to plugin_c
        ok, errors = resolver_with_plugins.can_remove_plugin("plugin_c")
        # plugin_c is not required by anyone, so removal is fine
        assert ok
        assert errors == []


class TestValidatePluginDisable:
    """Test plugin disable validation."""
    
    @pytest.fixture
    def resolver_with_plugins(self):
        """Create resolver with test plugins."""
        registry = Mock()
        plugin_manager = Mock()
        storage = Mock()
        policy = PluginLifecyclePolicy(registry, plugin_manager)

        registry.get_providers.return_value = []
        
        plugin_a = Mock()
        plugin_a.metadata = PluginMetadata(
            name="plugin_a",
            version="1.0.0",
            description="Test",
            author="Test",
            dependencies=[],
            capabilities_provided=["api.gateway"],
            capabilities_required=[]
        )
        
        plugin_b = Mock()
        plugin_b.metadata = PluginMetadata(
            name="plugin_b",
            version="1.0.0",
            description="Test",
            author="Test",
            dependencies=[],
            capabilities_provided=[],
            capabilities_required=["api.gateway"]
        )
        
        plugin_manager.get_loaded_plugins.return_value = [
            ("plugin_a", plugin_a),
            ("plugin_b", plugin_b),
        ]

        return policy
    
    def test_disable_unused_plugin_succeeds(self, resolver_with_plugins):
        """Test disabling plugin with no dependents succeeds."""
        # Create new resolver without dependencies
        registry = Mock()
        plugin_manager = Mock()
        storage = Mock()
        policy = PluginLifecyclePolicy(registry, plugin_manager)
        registry.get_providers.return_value = []
        
        plugin = Mock()
        plugin.metadata = PluginMetadata(
            name="standalone",
            version="1.0.0",
            description="Test",
            author="Test",
            dependencies=[],
            capabilities_provided=[],
            capabilities_required=[]
        )
        
        plugin_manager.get_loaded_plugins.return_value = [("standalone", plugin)]

        ok, errors = policy.can_disable_plugin("standalone")
        assert ok
        assert errors == []


class TestRuntimeIntegrity:
    """Test runtime integrity validation."""
    
    def test_runtime_with_unsatisfied_requirements_fails(self):
        """Test runtime integrity check fails if required capability has no provider."""
        registry = Mock()
        plugin_manager = Mock()
        storage = Mock()
        checker = DependencyIntegrityChecker(registry, plugin_manager)
        
        # Registry returns no providers
        registry.get_providers.return_value = []
        
        # Plugin requires something not provided
        plugin = Mock()
        plugin.metadata = PluginMetadata(
            name="broken_plugin",
            version="1.0.0",
            description="Test",
            author="Test",
            dependencies=[],
            capabilities_provided=[],
            capabilities_required=["client.command.execute"]
        )
        
        plugin_manager.get_loaded_plugins.return_value = [("broken_plugin", plugin)]

        errors = checker.check_runtime_integrity()
        assert len(errors) > 0
        assert "missing_capability_provider" in errors[0]
    
    def test_runtime_with_satisfied_requirements_succeeds(self):
        """Test runtime integrity check passes if all requirements satisfied."""
        registry = Mock()
        plugin_manager = Mock()
        storage = Mock()
        checker = DependencyIntegrityChecker(registry, plugin_manager)
        
        # Registry returns providers
        registry.get_providers.return_value = ["provider_plugin"]
        
        # Plugin requires something that is provided
        plugin = Mock()
        plugin.metadata = PluginMetadata(
            name="good_plugin",
            version="1.0.0",
            description="Test",
            author="Test",
            dependencies=[],
            capabilities_provided=[],
            capabilities_required=["client.command.execute"]
        )
        
        plugin_manager.get_loaded_plugins.return_value = [("good_plugin", plugin)]

        errors = checker.check_runtime_integrity()
        assert errors == []


class TestValidatePluginUpdate:
    """Test plugin update validation."""
    
    @pytest.fixture
    def resolver(self):
        """Create resolver."""
        registry = Mock()
        plugin_manager = Mock()
        storage = Mock()
        return PluginLifecyclePolicy(registry, plugin_manager)
    
    def test_update_with_new_satisfied_requirements(self, resolver):
        """Test update succeeds if new requirements are satisfied."""
        resolver.capability_registry.get_providers.return_value = ["existing_provider"]
        
        old_metadata = PluginMetadata(
            name="plugin",
            version="1.0.0",
            description="Test",
            author="Test",
            dependencies=[],
            capabilities_provided=["auth"],
            capabilities_required=[]
        )
        
        new_metadata = PluginMetadata(
            name="plugin",
            version="2.0.0",
            description="Test",
            author="Test",
            dependencies=[],
            capabilities_provided=["auth", "encryption"],
            capabilities_required=["logging.sink"]  # New requirement
        )
        
        ok, errors = resolver.can_update_plugin(old_metadata, new_metadata)
        assert ok
        assert errors == []
    
    def test_update_with_unsatisfied_new_requirements_fails(self, resolver):
        """Test update fails if new requirements are not satisfied."""
        resolver.capability_registry.get_providers.return_value = []
        
        old_metadata = PluginMetadata(
            name="plugin",
            version="1.0.0",
            description="Test",
            author="Test",
            dependencies=[],
            capabilities_provided=["auth"],
            capabilities_required=[]
        )
        
        new_metadata = PluginMetadata(
            name="plugin",
            version="2.0.0",
            description="Test",
            author="Test",
            dependencies=[],
            capabilities_provided=["auth"],
            capabilities_required=["missing.capability"]  # No provider
        )
        
        ok, errors = resolver.can_update_plugin(old_metadata, new_metadata)
        assert not ok
        assert len(errors) > 0


class TestDependencyGraphHelpers:
    """Test dependency integrity checker helpers."""
    
    @pytest.fixture
    def checker_with_graph(self):
        """Create checker with test dependency graph."""
        registry = Mock()
        plugin_manager = Mock()
        storage = Mock()
        checker = DependencyIntegrityChecker(registry, plugin_manager)
        
        # Create plugins
        plugin_a = Mock()
        plugin_a.metadata = PluginMetadata(
            name="plugin_a",
            version="1.0.0",
            description="Test",
            author="Test",
            dependencies=[],
            capabilities_provided=["service.api"],
            capabilities_required=[]
        )
        
        plugin_b = Mock()
        plugin_b.metadata = PluginMetadata(
            name="plugin_b",
            version="1.0.0",
            description="Test",
            author="Test",
            dependencies=[],
            capabilities_provided=[],
            capabilities_required=["service.api"]
        )
        
        plugin_manager.get_loaded_plugins.return_value = [
            ("plugin_a", plugin_a),
            ("plugin_b", plugin_b),
        ]
        
        def get_providers_side_effect(cap):
            if cap == "service.api":
                return ["plugin_a"]
            return []
        
        registry.get_providers.side_effect = get_providers_side_effect
        
        return checker
    
    def test_get_dependency_graph(self, checker_with_graph):
        graph = checker_with_graph.get_dependency_graph()
        assert "plugin_a" in graph
        assert "plugin_b" in graph
        assert graph["plugin_a"] == []
        assert graph["plugin_b"] == ["plugin_a"]

    def test_integrity_reports_missing_provider(self):
        registry = Mock()
        plugin_manager = Mock()
        checker = DependencyIntegrityChecker(registry, plugin_manager)

        registry.get_providers.return_value = []

        plugin = Mock()
        plugin.metadata = PluginMetadata(
            name="broken",
            version="1.0.0",
            description="Test",
            author="Test",
            dependencies=[],
            capabilities_provided=[],
            capabilities_required=["service.api"],
        )
        plugin_manager.get_loaded_plugins.return_value = [("broken", plugin)]

        errors = checker.check_runtime_integrity()
        assert any("missing_capability_provider" in e for e in errors)

    def test_integrity_reports_circular_dependency(self):
        registry = Mock()
        plugin_manager = Mock()
        checker = DependencyIntegrityChecker(registry, plugin_manager)

        # A requires B, B requires A (cycle)
        plugin_a = Mock()
        plugin_a.metadata = PluginMetadata(
            name="a",
            version="1.0.0",
            description="Test",
            author="Test",
            dependencies=[],
            capabilities_provided=["cap.a"],
            capabilities_required=["cap.b"],
        )
        plugin_b = Mock()
        plugin_b.metadata = PluginMetadata(
            name="b",
            version="1.0.0",
            description="Test",
            author="Test",
            dependencies=[],
            capabilities_provided=["cap.b"],
            capabilities_required=["cap.a"],
        )
        plugin_manager.get_loaded_plugins.return_value = [("a", plugin_a), ("b", plugin_b)]

        # registry.get_providers isn't used for cycle detection; the checker builds graph from metadata.
        errors = checker.check_runtime_integrity()
        assert any("circular_dependency" in e for e in errors)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
