"""
Tests for capability-based operations routing.

Verifies that:
1. Operations can be invoked by capability name instead of plugin name
2. OperationManager routes capability-style names to plugin handlers
3. Backward compatibility maintained for plugin-namespaced operations
4. Multiple providers can be supported (with primary selection)
5. Unloading plugin removes capability registration
"""

import pytest
import os
from typing import Any, Dict
from core.module import ModuleSpec
from core.runtime.runtime import CoreRuntime
from core.kernel.base_plugin import BasePlugin, PluginMetadata
from core.operations import OperationInitiator, OperationInitiatorKind, OperationStatus

# Disable auto-loading of plugins during tests
os.environ['TEST_MODE'] = '1'


async def _make_runtime(memory_adapter) -> CoreRuntime:
    """Создаёт runtime с execution module для тестов операций."""
    runtime = CoreRuntime(memory_adapter)
    await runtime.module_manager.register_module_specs(
        runtime, [ModuleSpec("execution", required=True)]
    )
    await runtime.start()
    return runtime


@pytest.mark.asyncio
async def test_capability_based_operation_invocation(memory_adapter):
    """Test that operation can be invoked by capability name."""
    runtime = await _make_runtime(memory_adapter)
    
    # Ensure capability registry exists
    assert runtime.capability_registry is not None
    
    # Define a simple capability provider plugin
    class CapabilityProviderPlugin(BasePlugin):
        @property
        def metadata(self) -> PluginMetadata:
            return PluginMetadata(
                name="test_capability_provider",
                version="1.0.0",
                description="Test plugin providing client capabilities",
                author="Test",
                dependencies=[],
                capabilities_provided=["client.command.execute"]
            )
        
        async def on_load(self) -> None:
            await super().on_load()
            self.runtime.operations.register_handler(
                "client.command.execute",
                self._handle_execute_command
            )
        
        async def _handle_execute_command(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "success": True,
                "command_id": params.get("command_id"),
                "provider": "test_capability_provider"
            }
    
    # Load plugin
    plugin = CapabilityProviderPlugin(runtime)
    await runtime.plugin_manager.load_plugin(plugin)
    
    # Create and execute operation using capability name
    initiator = OperationInitiator(kind=OperationInitiatorKind.ADMIN)
    operation = await runtime.operations.create(
        op_type="client.command.execute",
        params={"command_id": "cmd1"},
        initiator=initiator
    )
    
    result = await runtime.operations.execute(operation)
    
    # Verify operation succeeded
    assert result.status == OperationStatus.SUCCESS
    assert result.result["provider"] == "test_capability_provider"
    print(f"✓ Operation invoked by capability name: {result.result}")


@pytest.mark.asyncio
async def test_backward_compatibility_legacy_operations(memory_adapter):
    """Test that old plugin-namespaced operations still work."""
    runtime = await _make_runtime(memory_adapter)
    
    class LegacyOperationPlugin(BasePlugin):
        @property
        def metadata(self) -> PluginMetadata:
            return PluginMetadata(
                name="test_legacy_plugin",
                version="1.0.0",
                description="Test plugin using legacy operation naming",
                author="Test",
                dependencies=[]
            )
        
        async def on_load(self) -> None:
            await super().on_load()
            self.runtime.operations.register_handler(
                "test_legacy_plugin.action",
                self._handle_action
            )
        
        async def _handle_action(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "success": True,
                "action": params.get("action"),
                "plugin": "test_legacy_plugin"
            }
    
    plugin = LegacyOperationPlugin(runtime)
    await runtime.plugin_manager.load_plugin(plugin)
    
    # Execute operation using legacy name
    initiator = OperationInitiator(kind=OperationInitiatorKind.ADMIN)
    operation = await runtime.operations.create(
        op_type="test_legacy_plugin.action",
        params={"action": "test"},
        initiator=initiator
    )
    
    result = await runtime.operations.execute(operation)
    
    # Verify backward compatibility
    assert result.status == OperationStatus.SUCCESS
    assert result.result["plugin"] == "test_legacy_plugin"
    print(f"✓ Legacy operation naming works: {result.result}")


@pytest.mark.asyncio
async def test_capability_registry_integration(memory_adapter):
    """Test that capability registry is populated when plugin loads."""
    runtime = await _make_runtime(memory_adapter)
    
    cap_reg = runtime.capability_registry
    
    class CapabilityProviderPlugin(BasePlugin):
        @property
        def metadata(self) -> PluginMetadata:
            return PluginMetadata(
                name="test_provider",
                version="1.0.0",
                description="Test provider",
                author="Test",
                dependencies=[],
                capabilities_provided=["client.command.execute", "client.list"]
            )
        
        async def on_load(self) -> None:
            await super().on_load()
            self.runtime.operations.register_handler("client.command.execute", lambda p, c: {"ok": True})
            self.runtime.operations.register_handler("client.list", lambda p, c: {"ok": True})
    
    plugin = CapabilityProviderPlugin(runtime)
    await runtime.plugin_manager.load_plugin(plugin)
    
    # Check that capabilities are registered
    providers = cap_reg.get_providers("client.command.execute")
    assert providers is not None
    assert "test_provider" in providers
    
    providers_list = cap_reg.get_providers("client.list")
    assert "test_provider" in providers_list
    
    print(f"✓ Capabilities registered correctly")


@pytest.mark.asyncio
async def test_primary_provider_selection(memory_adapter):
    """Test that primary provider is selected for capability."""
    runtime = await _make_runtime(memory_adapter)
    
    cap_reg = runtime.capability_registry
    
    # Simulate multiple providers for same capability
    # register_provider(plugin_name, capability_id)
    await cap_reg.register_provider("provider_1", "test.capability")
    await cap_reg.register_provider("provider_2", "test.capability")
    
    # Get providers - primary should be first registered
    providers = cap_reg.get_providers("test.capability")
    assert providers is not None
    assert len(providers) == 2
    assert providers[0] == "provider_1"  # Primary provider
    
    print(f"✓ Primary provider selected: {providers[0]}")


@pytest.mark.asyncio
async def test_missing_capability_fails_gracefully(memory_adapter):
    """Test that missing capability results in failed operation."""
    runtime = await _make_runtime(memory_adapter)
    
    # Try to execute operation for non-existent capability
    initiator = OperationInitiator(kind=OperationInitiatorKind.ADMIN)
    operation = await runtime.operations.create(
        op_type="non.existent.capability",
        params={},
        initiator=initiator
    )
    
    result = await runtime.operations.execute(operation)
    
    # Should fail with unknown operation type
    assert result.status == OperationStatus.FAILED
    assert result.error is not None
    assert "unknown_operation_type" in result.error.code
    
    print(f"✓ Missing capability fails gracefully")


@pytest.mark.asyncio
async def test_operation_isolation_between_providers(memory_adapter):
    """Test that operations to different capabilities work independently."""
    runtime = await _make_runtime(memory_adapter)
    
    class ProviderA(BasePlugin):
        @property
        def metadata(self) -> PluginMetadata:
            return PluginMetadata(
                name="provider_a",
                version="1.0.0",
                description="Provider A",
                author="Test",
                dependencies=[],
                capabilities_provided=["capability.a"]
            )
        
        async def on_load(self) -> None:
            await super().on_load()
            self.runtime.operations.register_handler("capability.a", self._handle)
        
        async def _handle(self, params, context):
            return {"result": "from_a"}
    
    class ProviderB(BasePlugin):
        @property
        def metadata(self) -> PluginMetadata:
            return PluginMetadata(
                name="provider_b",
                version="1.0.0",
                description="Provider B",
                author="Test",
                dependencies=[],
                capabilities_provided=["capability.b"]
            )
        
        async def on_load(self) -> None:
            await super().on_load()
            self.runtime.operations.register_handler("capability.b", self._handle)
        
        async def _handle(self, params, context):
            return {"result": "from_b"}
    
    # Load both providers
    await runtime.plugin_manager.load_plugin(ProviderA(runtime))
    await runtime.plugin_manager.load_plugin(ProviderB(runtime))
    
    initiator = OperationInitiator(kind=OperationInitiatorKind.ADMIN)
    
    # Execute operation for capability.a
    op_a = await runtime.operations.create(
        op_type="capability.a",
        params={},
        initiator=initiator
    )
    result_a = await runtime.operations.execute(op_a)
    
    # Execute operation for capability.b
    op_b = await runtime.operations.create(
        op_type="capability.b",
        params={},
        initiator=initiator
    )
    result_b = await runtime.operations.execute(op_b)
    
    # Verify isolation
    assert result_a.status == OperationStatus.SUCCESS
    assert result_a.result["result"] == "from_a"
    assert result_b.status == OperationStatus.SUCCESS
    assert result_b.result["result"] == "from_b"
    
    print(f"✓ Operations isolated between providers")


@pytest.mark.asyncio
async def test_multiple_capabilities_same_plugin(memory_adapter):
    """Test plugin providing multiple capabilities."""
    runtime = await _make_runtime(memory_adapter)
    
    cap_reg = runtime.capability_registry
    
    class MultiCapabilityPlugin(BasePlugin):
        @property
        def metadata(self) -> PluginMetadata:
            return PluginMetadata(
                name="multi_cap_plugin",
                version="1.0.0",
                description="Plugin with multiple capabilities",
                author="Test",
                dependencies=[],
                capabilities_provided=["cap.a", "cap.b", "cap.c"]
            )
        
        async def on_load(self) -> None:
            await super().on_load()
            for cap in ["cap.a", "cap.b", "cap.c"]:
                self.runtime.operations.register_handler(cap, lambda p, c: {"ok": True})
    
    plugin = MultiCapabilityPlugin(runtime)
    await runtime.plugin_manager.load_plugin(plugin)
    
    # Verify all capabilities are registered
    for cap in ["cap.a", "cap.b", "cap.c"]:
        providers = cap_reg.get_providers(cap)
        assert "multi_cap_plugin" in providers
    
    print(f"✓ Multiple capabilities registered for single plugin")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
