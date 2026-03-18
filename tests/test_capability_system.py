"""
Test Capability System - проверка зависимостей между плагинами.

Сценарии:
1. Plugin A provides "cap_a" → A стартует
2. Plugin B requires "cap_a" → B стартует (cap_a available)
3. Plugin C requires "missing_cap" → C не стартует
4. Inspector показывает зависимости и unresolved capabilities
"""

import pytest
from typing import Optional

from core.kernel.base_plugin import BasePlugin, PluginMetadata
from core.plugins import PluginState
from core.runtime.runtime import CoreRuntime
from core.capability_registry import CapabilityRegistry


class CapabilityProviderPlugin(BasePlugin):
    """Плагин который предоставляет capability."""
    
    def __init__(self, runtime: Optional[CoreRuntime] = None):
        super().__init__(runtime)
        self._loaded_called = False
        self._started_called = False
    
    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="cap_provider",
            version="1.0.0",
            description="Provides test capability",
            author="Test",
            capabilities_provided=["test.capability_a", "test.capability_b"],
        )
    
    async def on_load(self) -> None:
        self._loaded_called = True
    
    async def on_start(self) -> None:
        self._started_called = True
    
    async def on_stop(self) -> None:
        pass
    
    async def on_unload(self) -> None:
        pass


class CapabilityConsumerPlugin(BasePlugin):
    """Плагин который требует capability."""
    
    def __init__(self, runtime: Optional[CoreRuntime] = None):
        super().__init__(runtime)
        self._started = False
    
    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="cap_consumer",
            version="1.0.0",
            description="Requires test capability",
            author="Test",
            capabilities_required=["test.capability_a"],
        )
    
    async def on_load(self) -> None:
        pass
    
    async def on_start(self) -> None:
        self._started = True
    
    async def on_stop(self) -> None:
        pass
    
    async def on_unload(self) -> None:
        pass


class MissingCapabilityConsumerPlugin(BasePlugin):
    """Плагин который требует несуществующий capability."""
    
    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="missing_cap_consumer",
            version="1.0.0",
            description="Requires missing capability",
            author="Test",
            capabilities_required=["test.nonexistent_capability"],
        )
    
    async def on_load(self) -> None:
        pass
    
    async def on_start(self) -> None:
        pass
    
    async def on_stop(self) -> None:
        pass
    
    async def on_unload(self) -> None:
        pass




@pytest.mark.asyncio
async def test_capability_registry_register():
    """Test CapabilityRegistry: регистрация capabilities."""
    registry = CapabilityRegistry()
    
    # Register provider
    await registry.register_provider("plugin_a", "cap_a")
    await registry.register_provider("plugin_b", "cap_b")
    
    # Check providers
    assert registry.get_providers("cap_a") == ["plugin_a"]
    assert registry.get_providers("cap_b") == ["plugin_b"]
    assert registry.get_providers("nonexistent") == []


@pytest.mark.asyncio
async def test_capability_registry_consumer():
    """Test CapabilityRegistry: регистрация потребителей."""
    registry = CapabilityRegistry()
    
    # Register consumer
    await registry.register_consumer("plugin_x", "cap_required")
    
    # Check consumers
    assert registry.get_required_capabilities("plugin_x") == ["cap_required"]
    assert registry.get_required_capabilities("plugin_y") == []


@pytest.mark.asyncio
async def test_capability_registry_validation():
    """Test CapabilityRegistry: валидация зависимостей."""
    registry = CapabilityRegistry()
    
    # Register provider
    await registry.register_provider("plugin_a", "cap_available")
    
    # Consumer with available capability
    await registry.register_consumer("plugin_b", "cap_available")
    ok, missing = await registry.validate_plugin_requirements("plugin_b")
    assert ok is True
    assert missing == []
    
    # Consumer with missing capability
    await registry.register_consumer("plugin_c", "cap_missing")
    ok, missing = await registry.validate_plugin_requirements("plugin_c")
    assert ok is False
    assert "cap_missing" in missing


@pytest.mark.asyncio
async def test_plugin_with_capabilities(memory_adapter):
    """Test плагины с capabilities стартуют корректно."""
    runtime = CoreRuntime(memory_adapter)
    
    # Create provider plugin
    provider = CapabilityProviderPlugin(runtime)
    
    # Load provider
    await runtime.plugin_manager.load_plugin(provider)
    
    # Check capabilities registered
    providers = runtime.capability_registry.get_providers("test.capability_a")
    assert "cap_provider" in providers
    providers = runtime.capability_registry.get_providers("test.capability_b")
    assert "cap_provider" in providers
    
    # Start provider
    await runtime.plugin_manager.start_plugin("cap_provider")
    state = await runtime.plugin_manager.get_plugin_state("cap_provider")
    assert state == PluginState.STARTED
    
    await runtime.stop()


@pytest.mark.asyncio
async def test_consumer_with_available_capability(memory_adapter):
    """Test потребитель стартует если capability доступна."""
    runtime = CoreRuntime(memory_adapter)
    
    # Load provider
    provider = CapabilityProviderPlugin(runtime)
    await runtime.plugin_manager.load_plugin(provider)
    await runtime.plugin_manager.start_plugin("cap_provider")
    
    # Load consumer
    consumer = CapabilityConsumerPlugin(runtime)
    await runtime.plugin_manager.load_plugin(consumer)
    
    # Start consumer - должен стартовать т.к. capability доступна
    await runtime.plugin_manager.start_plugin("cap_consumer")
    state = await runtime.plugin_manager.get_plugin_state("cap_consumer")
    assert state == PluginState.STARTED
    
    await runtime.stop()


@pytest.mark.asyncio
async def test_consumer_blocked_missing_capability(memory_adapter):
    """Test потребитель НЕ стартует если capability отсутствует."""
    runtime = CoreRuntime(memory_adapter)
    
    # Load consumer with missing capability
    consumer = MissingCapabilityConsumerPlugin(runtime)
    await runtime.plugin_manager.load_plugin(consumer)
    
    # Try to start - должен остаться в LOADED, не ERROR
    await runtime.plugin_manager.start_plugin("missing_cap_consumer")
    state = await runtime.plugin_manager.get_plugin_state("missing_cap_consumer")
    assert state == PluginState.LOADED  # Не стартовал, но не error
    
    # Check block reason
    reason = await runtime.plugin_manager.get_plugin_block_reason("missing_cap_consumer")
    assert reason is not None
    assert "test.nonexistent_capability" in reason.get("missing_capabilities", [])
    
    await runtime.stop()


@pytest.mark.asyncio
async def test_runtime_continues_with_blocked_plugin(memory_adapter):
    """Test runtime продолжает работать если плагин блокирован."""
    runtime = CoreRuntime(memory_adapter)
    await runtime.start()
    
    # Load provider
    provider = CapabilityProviderPlugin(runtime)
    await runtime.plugin_manager.load_plugin(provider)
    await runtime.plugin_manager.start_plugin("cap_provider")
    
    # Load consumer with missing capability
    consumer = MissingCapabilityConsumerPlugin(runtime)
    await runtime.plugin_manager.load_plugin(consumer)
    
    # Try to start missing capability consumer
    await runtime.plugin_manager.start_plugin("missing_cap_consumer")
    
    # Runtime должен все еще работать
    assert runtime.is_running
    
    # Provider должен быть started
    provider_state = await runtime.plugin_manager.get_plugin_state("cap_provider")
    assert provider_state == PluginState.STARTED
    
    await runtime.stop()


@pytest.mark.asyncio
async def test_inspector_shows_capabilities(memory_adapter):
    """Test Inspector показывает capabilities и unresolved."""
    runtime = CoreRuntime(memory_adapter)
    
    # Load provider
    provider = CapabilityProviderPlugin(runtime)
    await runtime.plugin_manager.load_plugin(provider)
    await runtime.plugin_manager.start_plugin("cap_provider")
    
    # Load consumer with missing capability
    consumer = MissingCapabilityConsumerPlugin(runtime)
    await runtime.plugin_manager.load_plugin(consumer)
    await runtime.plugin_manager.start_plugin("missing_cap_consumer")
    
    # Get plugin info via introspection
    from modules.admin.services.introspection import list_plugins
    plugins_info = await list_plugins(runtime)
    
    # Find provider info
    provider_info = next((p for p in plugins_info if p["name"] == "cap_provider"), None)
    assert provider_info is not None
    assert "test.capability_a" in provider_info["capabilities_provided"]
    assert "test.capability_b" in provider_info["capabilities_provided"]
    assert provider_info["started"] is True
    
    # Find consumer info
    consumer_info = next((p for p in plugins_info if p["name"] == "missing_cap_consumer"), None)
    assert consumer_info is not None
    assert "test.nonexistent_capability" in consumer_info["capabilities_required"]
    assert consumer_info["started"] is False
    assert len(consumer_info["unresolved_capabilities"]) > 0
    assert "Missing capabilities" in consumer_info.get("error", "")
    
    await runtime.stop()


@pytest.mark.asyncio
async def test_capability_unregister():
    """Test при выгрузке плагина capabilities удаляются."""
    registry = CapabilityRegistry()
    
    # Register provider
    await registry.register_provider("plugin_a", "cap_a")
    await registry.register_provider("plugin_a", "cap_b")
    
    # Check registered
    assert "plugin_a" in registry.get_providers("cap_a")
    assert "plugin_a" in registry.get_providers("cap_b")
    
    # Unregister
    await registry.unregister_plugin("plugin_a")
    
    # Check unregistered
    assert registry.get_providers("cap_a") == []
    assert registry.get_providers("cap_b") == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
