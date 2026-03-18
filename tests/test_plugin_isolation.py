"""
Test suite for Step 9: Plugin Execution Isolation.

Tests execution modes: in_process, process, container, remote.
Validates execution routing, error handling, timeouts.
Checks backward compatibility with existing operations.

NOTE: Process executor and Container executor tests have been refactored
to use execution/backends/ProcessBackend and ContainerBackend instead of
deprecated core.process_executor and core.container_executor modules.
"""

import pytest
import asyncio
import json
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from core.operations import (
    Operation, OperationStatus, OperationError, 
    OperationInitiator, OperationInitiatorKind
)
from core.execution_router import ExecutionRouter
from core.capability_protocol import ProviderMetadata
from core.capability_registry import CapabilityRegistry


class TestExecutionRouter:
    """Test ExecutionRouter routing logic based on execution_mode."""
    
    @pytest.fixture
    def runtime(self):
        """Create mock runtime."""
        runtime = Mock()
        runtime.service_registry = Mock()
        runtime.capability_registry = Mock()
        return runtime
    
    @pytest.fixture
    def router(self, runtime):
        """Create ExecutionRouter."""
        return ExecutionRouter(runtime)
    
    @pytest.fixture
    def operation(self):
        """Create sample operation."""
        initiator = OperationInitiator(
            kind=OperationInitiatorKind.ADMIN,
            user_id="test_admin"
        )
        return Operation(
            operation_id="op123",
            op_type="test.operation",
            params={"data": "test"},
            initiator=initiator
        )
    
    def test_router_init(self, router):
        """Test ExecutionRouter initialization."""
        assert router is not None
        assert hasattr(router, 'execute')
        assert hasattr(router, 'register_handler')
    
    @pytest.mark.asyncio
    async def test_register_handler(self, router):
        """Test handler registration."""
        handler = Mock()
        await router.register_handler("test.op", handler)
        # Handlers stored internally for in_process execution
        assert router is not None
    
    @pytest.mark.asyncio
    async def test_in_process_execution(self, router, operation):
        """Test in_process execution mode (direct handler call)."""
        handler = AsyncMock(return_value={"status": "success"})
        await router.register_handler("test.operation", handler)
        
        metadata = ProviderMetadata(
            plugin_name="test_plugin",
            provider_type="local",
            execution_mode="in_process"
        )
        
        result = await router.execute(operation, metadata)
        
        # Result is the direct handler return value (not wrapped)
        assert result == {"status": "success"}
        handler.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_in_process_with_none_metadata(self, router, operation):
        """Test in_process execution when metadata is None (backward compat)."""
        handler = AsyncMock(return_value={"status": "ok"})
        await router.register_handler("test.operation", handler)
        
        # No metadata provided (should default to in_process)
        result = await router.execute(operation, None)
        
        # Result is direct handler return value (not wrapped)
        assert result == {"status": "ok"}
        handler.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_process_execution_routing(self, router, operation):
        """Test process execution routing через ExecutionController."""
        # NOTE: ExecutionRouter теперь использует ExecutionController если доступен
        # Этот тест проверяет, что routing работает через ExecutionController
        from core.execution.controller import ExecutionControllerImpl
        from core.execution.backend import OperationResult
        
        # Создаём mock ExecutionController
        controller_mock = AsyncMock(spec=ExecutionControllerImpl)
        controller_mock.execute_operation = AsyncMock(
            return_value=OperationResult(
                ok=True,
                result={"status": "process_result"},
                backend="process"
            )
        )
        
        router.runtime.execution_controller = controller_mock
        
        metadata = ProviderMetadata(
            plugin_name="test_plugin",
            provider_type="local",
            execution_mode="process",
            process_config={"cmd": "python handler.py", "timeout": 30}
        )
        
        result = await router.execute(operation, metadata)
        assert result == {"status": "process_result"}
        controller_mock.execute_operation.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_container_execution_routing(self, router, operation):
        """Test container execution routing через ExecutionController."""
        # NOTE: ExecutionRouter теперь использует ExecutionController если доступен
        from core.execution.controller import ExecutionControllerImpl
        from core.execution.backend import OperationResult
        
        # Создаём mock ExecutionController
        controller_mock = AsyncMock(spec=ExecutionControllerImpl)
        controller_mock.execute_operation = AsyncMock(
            return_value=OperationResult(
                ok=True,
                result={"status": "container_result"},
                backend="container"
            )
        )
        
        router.runtime.execution_controller = controller_mock
        
        metadata = ProviderMetadata(
            plugin_name="test_plugin",
            provider_type="local",
            execution_mode="container",
            container_config={"image": "test:latest", "timeout": 30}
        )
        
        result = await router.execute(operation, metadata)
        assert result == {"status": "container_result"}
        controller_mock.execute_operation.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_unknown_execution_mode(self, router, operation):
        """Test unknown execution mode raises error."""
        handler = AsyncMock(return_value={"status": "fallback"})
        await router.register_handler("test.operation", handler)
        
        metadata = ProviderMetadata(
            plugin_name="test_plugin",
            provider_type="local",
            execution_mode="unknown_mode"  # Unknown mode
        )
        
        # Should raise ExecutionRouterError for unknown mode
        from core.execution_router import ExecutionRouterError
        with pytest.raises(ExecutionRouterError):
            await router.execute(operation, metadata)


class TestExecutionModes:
    """Test different execution modes for operations."""
    
    @pytest.fixture
    def mock_registry(self):
        """Create mock capability registry."""
        registry = Mock(spec=CapabilityRegistry)
        registry.get_all_providers_for_capability = Mock(return_value=[])
        registry.provider_info_to_metadata = Mock()
        return registry
    
    @pytest.fixture
    def operation_manager_mock(self, mock_registry):
        """Create mock OperationManager with routing."""
        runtime = Mock()
        runtime.capability_registry = mock_registry
        runtime.service_registry = Mock()
        
        # We'll test routing behavior through mock
        manager = Mock()
        manager._execution_router = ExecutionRouter(runtime)
        manager._handlers = {}
        return manager
    
    def test_default_execution_mode_is_in_process(self):
        """Test that default execution mode is in_process."""
        metadata = ProviderMetadata(
            plugin_name="test",
            provider_type="local"
        )
        assert metadata.execution_mode == "in_process"
    
    def test_execution_mode_from_metadata(self):
        """Test getting execution mode from metadata."""
        modes = ["in_process", "process", "container", "remote"]
        for mode in modes:
            metadata = ProviderMetadata(
                plugin_name="test",
                provider_type="local",
                execution_mode=mode
            )
            assert metadata.execution_mode == mode
    
    def test_process_config_storage(self):
        """Test process config can be stored in metadata."""
        config = {"cmd": "python handler.py", "timeout": 60}
        metadata = ProviderMetadata(
            plugin_name="test",
            provider_type="local",
            execution_mode="process",
            process_config=config
        )
        assert metadata.process_config == config
    
    def test_container_config_storage(self):
        """Test container config can be stored in metadata."""
        config = {
            "image": "ubuntu:22.04",
            "timeout": 120,
            "env": {"DEBUG": "true"}
        }
        metadata = ProviderMetadata(
            plugin_name="test",
            provider_type="local",
            execution_mode="container",
            container_config=config
        )
        assert metadata.container_config == config


class TestBackwardCompatibility:
    """Test backward compatibility with existing operations."""
    
    def test_operations_without_execution_mode(self):
        """Test operations created without execution_mode still work."""
        # Old operations don't have execution_mode
        initiator = OperationInitiator(
            kind=OperationInitiatorKind.ADMIN,
            user_id="test_admin"
        )
        operation = Operation(
            operation_id="old_op",
            op_type="legacy.task",
            params={"param": "value"},
            initiator=initiator
        )
        
        assert operation is not None
        assert operation.type == "legacy.task"
    
    def test_metadata_defaults_to_in_process(self):
        """Test ProviderMetadata defaults to in_process."""
        # When existing code doesn't specify execution_mode
        metadata = ProviderMetadata(
            plugin_name="legacy_plugin",
            provider_type="local"
        )
        
        assert metadata.execution_mode == "in_process"
        assert metadata.process_config is None
        assert metadata.container_config is None
    
    @pytest.mark.asyncio
    async def test_handlers_registered_for_in_process(self):
        """Test handlers are still registered for in_process execution."""
        router = ExecutionRouter(Mock())
        handler = Mock()
        
        await router.register_handler("test.op", handler)
        # If no exception thrown, registration succeeded
        assert True


class TestExecutionErrors:
    """Test error handling in execution modes."""
    
    @pytest.fixture
    def executor(self):
        """Create ExecutionRouter."""
        return ExecutionRouter(Mock())
    
    @pytest.fixture
    def operation(self):
        """Create sample operation."""
        initiator = OperationInitiator(
            kind=OperationInitiatorKind.ADMIN,
            user_id="test_admin"
        )
        return Operation(
            operation_id="error_op",
            op_type="test.error",
            params={},
            initiator=initiator
        )
    
    @pytest.mark.asyncio
    async def test_handler_exception_caught(self, executor, operation):
        """Test exceptions from handler are propagated."""
        handler = AsyncMock(side_effect=ValueError("Handler error"))
        await executor.register_handler("test.error", handler)
        
        metadata = ProviderMetadata(
            plugin_name="test",
            provider_type="local",
            execution_mode="in_process"
        )
        
        # Handler error should be wrapped in ExecutionRouterError
        from core.execution_router import ExecutionRouterError
        with pytest.raises(ExecutionRouterError):
            await executor.execute(operation, metadata)
    
    @pytest.mark.asyncio
    async def test_missing_handler_in_process(self, executor, operation):
        """Test missing handler in in_process mode raises error."""
        metadata = ProviderMetadata(
            plugin_name="test",
            provider_type="local",
            execution_mode="in_process"
        )
        
        # No handler registered for this operation type
        from core.execution_router import ExecutionRouterError
        with pytest.raises(ExecutionRouterError):
            await executor.execute(operation, metadata)


class TestCapabilityRegistryIntegration:
    """Test integration with CapabilityRegistry for execution_mode support."""
    
    @pytest.fixture
    def registry(self):
        """Create CapabilityRegistry."""
        return CapabilityRegistry()
    
    @pytest.mark.asyncio
    async def test_register_provider_with_execution_mode(self, registry):
        """Test registering provider with execution_mode."""
        await registry.register_provider(
            plugin_name="test_plugin",
            capability_id="test.capability",
            execution_mode="process",
            process_config={"cmd": "python handler.py"}
        )
        
        providers = registry.get_providers("test.capability")
        assert "test_plugin" in providers
    
    @pytest.mark.asyncio
    async def test_provider_info_includes_execution_mode(self, registry):
        """Test provider info includes execution_mode."""
        await registry.register_provider(
            plugin_name="container_plugin",
            capability_id="test.container",
            execution_mode="container",
            container_config={"image": "ubuntu"}
        )
        
        info = registry.get_provider_info("test.container", "container_plugin")
        assert info["execution_mode"] == "container"
        assert info["container_config"]["image"] == "ubuntu"
    
    @pytest.mark.asyncio
    async def test_provider_info_to_metadata_conversion(self, registry):
        """Test converting provider_info dict to ProviderMetadata."""
        await registry.register_provider(
            plugin_name="convert_test",
            capability_id="test.convert",
            execution_mode="process",
            process_config={"timeout": 45}
        )
        
        provider_info = registry.get_provider_info("test.convert", "convert_test")
        metadata = registry.provider_info_to_metadata(provider_info)
        
        assert isinstance(metadata, ProviderMetadata)
        assert metadata.execution_mode == "process"
        assert metadata.process_config["timeout"] == 45
    
    @pytest.mark.asyncio
    async def test_update_provider_metadata_with_execution_mode(self, registry):
        """Test updating provider metadata with execution_mode."""
        await registry.register_provider(
            plugin_name="update_test",
            capability_id="test.update"
        )
        
        await registry.update_provider_metadata(
            plugin_name="update_test",
            capability_id="test.update",
            execution_mode="container",
            container_config={"image": "python:3.11"}
        )
        
        info = registry.get_provider_info("test.update", "update_test")
        assert info["execution_mode"] == "container"
        assert info["container_config"]["image"] == "python:3.11"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
