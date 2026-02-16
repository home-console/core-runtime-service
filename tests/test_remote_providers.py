"""
Tests for remote capability providers.

Verifies that:
1. Remote providers can be declared in metadata
2. Operations are executed via HTTP to remote providers
3. Local providers take precedence over remote
4. Remote provider errors are handled gracefully
5. Inspector shows provider types correctly
"""

import pytest
import os
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any, Dict, Optional

os.environ['TEST_MODE'] = '1'

from core.runtime import CoreRuntime
from core.base_plugin import BasePlugin, PluginMetadata
from core.remote_provider import RemoteCapabilityProvider
from core.operations import OperationInitiator, OperationInitiatorKind, OperationStatus
from core.remote_executor import RemoteOperationExecutor


class MockRemoteProvider(RemoteCapabilityProvider):
    """Mock remote capability provider for testing."""
    
    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="mock_remote_provider",
            version="1.0.0",
            description="Mock remote provider",
            author="Test",
            dependencies=[],
            capabilities_provided=["test.remote.execute"],
            remote_config={
                "base_url": "http://localhost:9000",
                "timeout": 5,
            }
        )


class LocalCapabilityProvider(BasePlugin):
    """Local capability provider for testing."""
    
    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="local_provider",
            version="1.0.0",
            description="Local provider",
            author="Test",
            dependencies=[],
            capabilities_provided=["test.local.execute"]
        )
    
    async def on_load(self) -> None:
        await super().on_load()
        self.runtime.operations.register_handler(
            "test.local.execute",
            self._handle_local
        )
    
    async def _handle_local(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        return {"result": "from_local_handler", "plugin": "local_provider"}


@pytest.mark.asyncio
async def test_remote_provider_metadata_validation(memory_adapter):
    """Test that remote provider requires remote_config in metadata."""
    runtime = CoreRuntime(memory_adapter)
    await runtime.start()
    
    # Create remote provider with proper config
    provider = MockRemoteProvider(runtime)
    
    # Should not raise on load
    await runtime.plugin_manager.load_plugin(provider)
    assert "mock_remote_provider" in runtime.plugin_manager.list_plugins()
    
    await runtime.stop()


@pytest.mark.asyncio
async def test_remote_provider_registered_in_capability_registry(memory_adapter):
    """Test that remote provider is registered with correct type in registry."""
    runtime = CoreRuntime(memory_adapter)
    await runtime.start()
    
    provider = MockRemoteProvider(runtime)
    await runtime.plugin_manager.load_plugin(provider)
    
    cap_reg = runtime.capability_registry
    
    # Get provider info
    provider_info = cap_reg.get_provider_info("test.remote.execute", "mock_remote_provider")
    
    assert provider_info is not None
    assert provider_info["type"] == "remote"
    assert provider_info["remote_config"]["base_url"] == "http://localhost:9000"
    assert provider_info["remote_config"]["timeout"] == 5
    
    await runtime.stop()


@pytest.mark.asyncio
async def test_remote_operation_execution_successful(memory_adapter):
    """Test successful remote operation execution via HTTP."""
    runtime = CoreRuntime(memory_adapter)
    await runtime.start()
    
    provider = MockRemoteProvider(runtime)
    await runtime.plugin_manager.load_plugin(provider)
    
    # Create mock response object
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "status": "success",
        "result": {"data": "from_remote_server"}
    }
    
    # Mock the HTTP client
    with patch('httpx.AsyncClient') as mock_client_class:
        # Create mock client instance
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client
        
        # Create and execute operation
        initiator = OperationInitiator(kind=OperationInitiatorKind.ADMIN)
        operation = await runtime.operations.create(
            op_type="test.remote.execute",
            params={"action": "test"},
            initiator=initiator
        )
        
        result = await runtime.operations.execute(operation)
        
        # Verify successful execution
        assert result.status == OperationStatus.SUCCESS
        assert result.result["data"] == "from_remote_server"
        
        # Verify HTTP was called
        mock_client.post.assert_called_once()
    
    await runtime.stop()


@pytest.mark.asyncio
async def test_remote_operation_execution_error(memory_adapter):
    """Test remote operation error handling."""
    runtime = CoreRuntime(memory_adapter)
    await runtime.start()
    
    provider = MockRemoteProvider(runtime)
    await runtime.plugin_manager.load_plugin(provider)
    
    # Create mock response object with error
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "status": "error",
        "error": {
            "code": "not_found",
            "message": "Resource not found"
        }
    }
    
    # Mock the HTTP client
    with patch('httpx.AsyncClient') as mock_client_class:
        # Create mock client instance
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client
        
        # Create and execute operation
        initiator = OperationInitiator(kind=OperationInitiatorKind.ADMIN)
        operation = await runtime.operations.create(
            op_type="test.remote.execute",
            params={},
            initiator=initiator
        )
        
        result = await runtime.operations.execute(operation)
        
        # Verify error handling
        assert result.status == OperationStatus.FAILED
        assert result.error.code == "not_found"
        assert "Resource not found" in result.error.message
    
    await runtime.stop()


@pytest.mark.asyncio
async def test_local_provider_preferred_over_remote(memory_adapter):
    """Test that local providers take precedence over remote."""
    runtime = CoreRuntime(memory_adapter)
    await runtime.start()
    
    # Create both local and remote providers for same capability
    
    class LocalAndRemote(BasePlugin):
        @property
        def metadata(self) -> PluginMetadata:
            return PluginMetadata(
                name="local_solo",
                version="1.0.0",
                description="Local",
                author="Test",
                dependencies=[],
                capabilities_provided=["test.priority"]
            )
        
        async def on_load(self) -> None:
            await super().on_load()
            async def handle_priority(params, context):
                return {"source": "local"}
            self.runtime.operations.register_handler(
                "test.priority",
                handle_priority
            )
    
    class RemoteDuplicate(RemoteCapabilityProvider):
        @property
        def metadata(self) -> PluginMetadata:
            return PluginMetadata(
                name="remote_duplicate",
                version="1.0.0",
                description="Remote",
                author="Test",
                dependencies=[],
                capabilities_provided=["test.priority"],
                remote_config={
                    "base_url": "http://localhost:9001",
                    "timeout": 5,
                }
            )
    
    # Load both
    local = LocalAndRemote(runtime)
    remote = RemoteDuplicate(runtime)
    
    await runtime.plugin_manager.load_plugin(local)
    await runtime.plugin_manager.load_plugin(remote)
    
    # Verify that local is primary
    cap_reg = runtime.capability_registry
    providers = cap_reg.get_providers("test.priority")
    
    # Local should come first
    assert providers[0] == "local_solo"
    assert "remote_duplicate" in providers
    
    # Execute should use local (not HTTP)
    initiator = OperationInitiator(kind=OperationInitiatorKind.ADMIN)
    operation = await runtime.operations.create(
        op_type="test.priority",
        params={},
        initiator=initiator
    )
    
    # Should use local handler, no HTTP needed
    result = await runtime.operations.execute(operation)
    assert result.status == OperationStatus.SUCCESS
    assert result.result["source"] == "local"
    
    await runtime.stop()


@pytest.mark.asyncio
async def test_inspector_shows_provider_types(memory_adapter):
    """Test that Inspector shows whether providers are local or remote."""
    runtime = CoreRuntime(memory_adapter)
    await runtime.start()
    
    # Load mixed providers
    local = LocalCapabilityProvider(runtime)
    remote = MockRemoteProvider(runtime)
    
    await runtime.plugin_manager.load_plugin(local)
    await runtime.plugin_manager.load_plugin(remote)
    
    from modules.admin.services.introspection import list_capabilities
    capabilities = await list_capabilities(runtime)
    
    # Find capabilities
    local_cap = next((c for c in capabilities if c["id"] == "test.local.execute"), None)
    remote_cap = next((c for c in capabilities if c["id"] == "test.remote.execute"), None)
    
    # Verify local capability
    assert local_cap is not None
    assert local_cap["local_provider_count"] == 1
    assert local_cap["remote_provider_count"] == 0
    assert local_cap["providers"][0]["type"] == "local"
    
    # Verify remote capability
    assert remote_cap is not None
    assert remote_cap["local_provider_count"] == 0
    assert remote_cap["remote_provider_count"] == 1
    assert remote_cap["providers"][0]["type"] == "remote"
    assert remote_cap["providers"][0]["base_url"] == "http://localhost:9000"
    
    await runtime.stop()


@pytest.mark.asyncio
async def test_network_error_handling(memory_adapter):
    """Test graceful handling of network errors."""
    runtime = CoreRuntime(memory_adapter)
    await runtime.start()
    
    provider = MockRemoteProvider(runtime)
    await runtime.plugin_manager.load_plugin(provider)
    
    import httpx
    
    with patch('httpx.AsyncClient') as mock_client_class:
        # Create mock client that raises error
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client
        
        # Create and execute operation
        initiator = OperationInitiator(kind=OperationInitiatorKind.ADMIN)
        operation = await runtime.operations.create(
            op_type="test.remote.execute",
            params={},
            initiator=initiator
        )
        
        result = await runtime.operations.execute(operation)
        
        # Should fail gracefully
        assert result.status == OperationStatus.FAILED
        assert "Cannot connect to remote provider" in result.error.message
    
    await runtime.stop()


@pytest.mark.asyncio
async def test_timeout_handling(memory_adapter):
    """Test timeout handling for remote operations."""
    runtime = CoreRuntime(memory_adapter)
    await runtime.start()
    
    provider = MockRemoteProvider(runtime)
    await runtime.plugin_manager.load_plugin(provider)
    
    import httpx
    
    with patch('httpx.AsyncClient') as mock_client_class:
        # Create mock client that raises timeout
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.TimeoutException("Request timeout")
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client
        
        # Create and execute operation with short timeout
        initiator = OperationInitiator(kind=OperationInitiatorKind.ADMIN)
        operation = await runtime.operations.create(
            op_type="test.remote.execute",
            params={},
            initiator=initiator
        )
        
        result = await runtime.operations.execute(operation)
        
        # Should fail gracefully
        assert result.status == OperationStatus.FAILED
        assert "timeout" in result.error.message.lower()
    
    await runtime.stop()


@pytest.mark.asyncio
async def test_can_remove_local_keep_remote(memory_adapter):
    """
    DoD Q1: Can you remove local plugin and keep remote working?
    
    Test that unloading local provider doesn't break capability -
    remote provider takes over.
    """
    runtime = CoreRuntime(memory_adapter)
    await runtime.start()
    
    # Create local provider for same capability
    class LocalTestProvider(BasePlugin):
        @property
        def metadata(self) -> PluginMetadata:
            return PluginMetadata(
                name="local_test",
                version="1.0.0",
                description="Local",
                author="Test",
                dependencies=[],
                capabilities_provided=["test.hybrid"]
            )
        
        async def on_load(self) -> None:
            await super().on_load()
            async def handle_hybrid(params, context):
                return {"source": "local"}
            self.runtime.operations.register_handler(
                "test.hybrid",
                handle_hybrid
            )
    
    class RemoteTestProvider(RemoteCapabilityProvider):
        @property
        def metadata(self) -> PluginMetadata:
            return PluginMetadata(
                name="remote_test",
                version="1.0.0",
                description="Remote",
                author="Test",
                dependencies=[],
                capabilities_provided=["test.hybrid"],
                remote_config={
                    "base_url": "http://localhost:9002",
                    "timeout": 5,
                }
            )
    
    # Load both
    local = LocalTestProvider(runtime)
    remote = RemoteTestProvider(runtime)
    
    await runtime.plugin_manager.load_plugin(local)
    await runtime.plugin_manager.load_plugin(remote)
    
    # Verify local is used
    cap_reg = runtime.capability_registry
    providers = cap_reg.get_providers("test.hybrid")
    assert providers[0] == "local_test"
    
    # Unload local
    await runtime.plugin_manager.unload_plugin("local_test")
    
    # Remote should now be primary
    providers = cap_reg.get_providers("test.hybrid")
    assert providers[0] == "remote_test"
    
    # Mock the HTTP response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"status": "success", "result": {"source": "remote"}}
    
    with patch('httpx.AsyncClient') as mock_client_class:
        # Create mock client instance
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client
        
        # Execute operation - should now use remote
        initiator = OperationInitiator(kind=OperationInitiatorKind.ADMIN)
        operation = await runtime.operations.create(
            op_type="test.hybrid",
            params={},
            initiator=initiator
        )
        
        result = await runtime.operations.execute(operation)
        
        # Should succeed using remote
        assert result.status == OperationStatus.SUCCESS
        assert result.result["source"] == "remote"
    
    await runtime.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
