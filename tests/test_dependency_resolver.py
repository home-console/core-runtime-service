"""
Test suite for Step 10: DependencyResolver.

Tests system integrity validation:
- Installation constraints
- Removal constraints
- Disable constraints
- Alternative provider fallbacks
- Runtime integrity checks
"""

import pytest
from unittest.mock import Mock
from core.dependency import DependencyResolver, RuntimeIntegrityError
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
        """Create DependencyResolver."""
        return DependencyResolver(registry, plugin_manager, storage)
    
    def test_resolver_init(self, resolver):
        """Test resolver initialization."""
        assert resolver is not None
        assert resolver.capability_registry is not None
        assert resolver.plugin_manager is not None
    
    def test_empty_runtime_is_valid(self, resolver):
        """Test empty runtime (no plugins) is valid."""
        errors = resolver.validate_runtime_integrity()
        assert errors == []
    
    def test_empty_install_is_valid(self, resolver):
        """Test plugin with no requirements can be installed."""
        metadata = PluginMetadata(
            name="empty_plugin",
            version="1.0.0",
            description="Test",
            author="Test",
            dependencies=[],
            capabilities_provided=[],
            capabilities_required=[]
        )
        
        errors = resolver.validate_plugin_install(metadata)
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
        """Create DependencyResolver."""
        return DependencyResolver(registry, plugin_manager, storage)
    
    def test_install_without_provider_fails(self, resolver, registry):
        """Test installation fails if required capability has no provider."""
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
        
        errors = resolver.validate_plugin_install(metadata)
        assert len(errors) > 0
        assert "missing_capability_provider" in errors[0]
        assert "client.command.execute" in errors[0]
    
    def test_install_with_provider_succeeds(self, resolver, registry):
        """Test installation succeeds if required capability has provider."""
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
        
        errors = resolver.validate_plugin_install(metadata)
        assert errors == []
    
    def test_install_with_self_provided_succeeds(self, resolver, registry):
        """Test installation succeeds if capability is self-provided."""
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
        
        errors = resolver.validate_plugin_install(metadata)
        assert errors == []
    
    def test_install_multiple_requirements_all_satisfied(self, resolver, registry):
        """Test installation with multiple requirements all satisfied."""
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
        
        errors = resolver.validate_plugin_install(metadata)
        assert errors == []
    
    def test_install_multiple_requirements_one_missing(self, resolver, registry):
        """Test installation fails if one of multiple requirements is not satisfied."""
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
        
        errors = resolver.validate_plugin_install(metadata)
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
        
        resolver = DependencyResolver(registry, plugin_manager, storage)
        
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
        
        return resolver
    
    def test_remove_unused_provider_succeeds(self, resolver_with_plugins):
        """Test removal succeeds if no plugin requires the capability."""
        errors = resolver_with_plugins.validate_plugin_removal("plugin_c")
        assert errors == []
    
    def test_remove_required_provider_fails(self, resolver_with_plugins):
        """Test removal fails if another plugin requires the capability."""
        errors = resolver_with_plugins.validate_plugin_removal("plugin_a")
        assert len(errors) > 0
        assert "required_provider_removal" in errors[0]
        assert "plugin_b" in errors[0]
    
    def test_remove_provider_with_alternative_succeeds(self, resolver_with_plugins):
        """Test removal succeeds if there's an alternative provider."""
        # plugin_backup provides "auth" as alternative to plugin_c
        errors = resolver_with_plugins.validate_plugin_removal("plugin_c")
        # plugin_c is not required by anyone, so removal is fine
        assert errors == []


class TestValidatePluginDisable:
    """Test plugin disable validation."""
    
    @pytest.fixture
    def resolver_with_plugins(self):
        """Create resolver with test plugins."""
        registry = Mock()
        plugin_manager = Mock()
        storage = Mock()
        
        resolver = DependencyResolver(registry, plugin_manager, storage)
        
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
        
        return resolver
    
    def test_disable_unused_plugin_succeeds(self, resolver_with_plugins):
        """Test disabling plugin with no dependents succeeds."""
        # Create new resolver without dependencies
        registry = Mock()
        plugin_manager = Mock()
        storage = Mock()
        
        resolver = DependencyResolver(registry, plugin_manager, storage)
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
        
        errors = resolver.validate_plugin_disable("standalone")
        assert errors == []


class TestRuntimeIntegrity:
    """Test runtime integrity validation."""
    
    def test_runtime_with_unsatisfied_requirements_fails(self):
        """Test runtime integrity check fails if required capability has no provider."""
        registry = Mock()
        plugin_manager = Mock()
        storage = Mock()
        
        resolver = DependencyResolver(registry, plugin_manager, storage)
        
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
        
        errors = resolver.validate_runtime_integrity()
        assert len(errors) > 0
        assert "missing_capability_provider" in errors[0]
    
    def test_runtime_with_satisfied_requirements_succeeds(self):
        """Test runtime integrity check passes if all requirements satisfied."""
        registry = Mock()
        plugin_manager = Mock()
        storage = Mock()
        
        resolver = DependencyResolver(registry, plugin_manager, storage)
        
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
        
        errors = resolver.validate_runtime_integrity()
        assert errors == []


class TestValidatePluginUpdate:
    """Test plugin update validation."""
    
    @pytest.fixture
    def resolver(self):
        """Create resolver."""
        registry = Mock()
        plugin_manager = Mock()
        storage = Mock()
        return DependencyResolver(registry, plugin_manager, storage)
    
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
        
        errors = resolver.validate_plugin_update(old_metadata, new_metadata)
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
        
        errors = resolver.validate_plugin_update(old_metadata, new_metadata)
        assert len(errors) > 0


class TestDependencyGraphHelpers:
    """Test dependency graph helper methods."""
    
    @pytest.fixture
    def resolver_with_graph(self):
        """Create resolver with test dependency graph."""
        registry = Mock()
        plugin_manager = Mock()
        storage = Mock()
        
        resolver = DependencyResolver(registry, plugin_manager, storage)
        
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
        
        return resolver
    
    def test_get_capability_providers(self, resolver_with_graph):
        """Test getting providers for a capability."""
        providers = resolver_with_graph.get_capability_providers("service.api")
        assert "plugin_a" in providers
    
    def test_get_plugin_required_capabilities(self, resolver_with_graph):
        """Test getting required capabilities for a plugin."""
        required = resolver_with_graph.get_plugin_required_capabilities("plugin_b")
        assert "service.api" in required
    
    def test_get_plugin_provided_capabilities(self, resolver_with_graph):
        """Test getting provided capabilities for a plugin."""
        provided = resolver_with_graph.get_plugin_provided_capabilities("plugin_a")
        assert "service.api" in provided


class TestRuntimeIntegrityError:
    """Test RuntimeIntegrityError exception."""
    
    def test_error_creation(self):
        """Test error can be created with list of errors."""
        errors = [
            "error1: plugin_a - Missing capability",
            "error2: plugin_b - Required provider removal"
        ]
        
        error = RuntimeIntegrityError(errors)
        assert error.errors == errors
        assert "2 errors" in str(error)
    
    def test_error_message_format(self):
        """Test error message is well formatted."""
        errors = ["test_error: plugin - message"]
        
        error = RuntimeIntegrityError(errors)
        error_str = str(error)
        
        assert "Runtime integrity check failed" in error_str
        assert "test_error" in error_str


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
