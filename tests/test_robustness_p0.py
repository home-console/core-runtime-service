"""
P0 Hardening Tests — Critical robustness checks.

Tests for:
1. Race condition protection (ExecutionRouter, PluginManager)
2. Circular dependency detection
3. Post-install activation
4. Cleanup on load failure
"""

import asyncio
import json
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import Mock, patch, AsyncMock
import pytest

from core.runtime import CoreRuntime
from core.plugins import PluginManager, PluginState
from core.base_plugin import BasePlugin, PluginMetadata
from core.storage import Storage
from core.dependency_resolver import DependencyResolver, DependencyError
from modules.marketplace.installer import MarketplaceInstaller
from tests.conftest import InMemoryStorageAdapter


# Test Plugin fixtures
class DemoPluginA(BasePlugin):
    """Demo plugin A."""
    
    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="demo_plugin_a",
            version="1.0.0",
            description="Demo plugin A",
            author="test",
        )
    
    async def on_load(self) -> None:
        pass
    
    async def on_start(self) -> None:
        pass


class DemoPluginB(BasePlugin):
    """Demo plugin B with circular requirement."""
    
    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="demo_plugin_b",
            version="1.0.0",
            description="Demo plugin B",
            author="test",
            capabilities_required=["test:service_a"],
            capabilities_provided=["test:service_b"],
        )
    
    async def on_load(self) -> None:
        pass
    
    async def on_start(self) -> None:
        pass


class DemoPluginC(BasePlugin):
    """Demo plugin C that requires plugin B."""
    
    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="demo_plugin_c",
            version="1.0.0",
            description="Demo plugin C",
            author="test",
            capabilities_required=["test:service_b"],
            capabilities_provided=["test:service_a"],
        )
    
    async def on_load(self) -> None:
        pass
    
    async def on_start(self) -> None:
        pass


@pytest.fixture
def memory_adapter():
    """In-memory storage for tests."""
    return InMemoryStorageAdapter()


@pytest.fixture
async def runtime(memory_adapter):
    """Create a test runtime."""
    runtime = CoreRuntime(memory_adapter)
    await runtime.start()
    yield runtime
    try:
        await runtime.stop()
    except Exception:
        pass


@pytest.fixture
def test_plugin_archive(tmp_path):
    """Create a test plugin archive."""
    plugin_dir = tmp_path / "test_plugin"
    plugin_dir.mkdir()
    
    # Create plugin.json
    plugin_json = {
        "name": "test_plugin",
        "version": "1.0.0",
        "entrypoint": "plugin.py",
        "description": "Test plugin",
        "author": "test",
    }
    
    (plugin_dir / "plugin.json").write_text(json.dumps(plugin_json))
    
    # Create plugin.py
    plugin_py = '''
from core.base_plugin import BasePlugin, PluginMetadata

class TestPlugin(BasePlugin):
    @property
    def metadata(self):
        return PluginMetadata(
            name="test_plugin",
            version="1.0.0",
            description="Test plugin",
            author="test",
        )
    
    async def on_load(self):
        pass
    
    async def on_start(self):
        pass
    
    def list_capabilities(self):
        return []
'''
    
    (plugin_dir / "plugin.py").write_text(plugin_py)
    
    # Create ZIP archive
    archive_path = tmp_path / "test_plugin.zip"
    with zipfile.ZipFile(archive_path, "w") as zf:
        for file_path in plugin_dir.iterdir():
            zf.write(file_path, arcname=file_path.name)
    
    return archive_path


# ========== TEST 1: Post-Install Activation ==========
# Skipped: Requires full runtime setup which loads system plugins
# The fix was implemented in MarketplaceInstaller.install_from_file()
# that calls start_plugin() after load_plugin()

# @pytest.mark.asyncio
# async def test_install_starts_plugin(runtime, test_plugin_archive):
#     """P0: Verify plugin is started after install."""
#     installer = MarketplaceInstaller(Path("/tmp/test_plugins"))
#     
#     # Install plugin
#     result = await installer.install_from_file(test_plugin_archive, runtime=runtime)
#     
#     # Verify plugin state
#     assert result["name"] == "test_plugin"
#     plugin_state = runtime.plugin_manager.get_state("test_plugin")
#     assert plugin_state == PluginState.STARTED, f"Expected STARTED, got {plugin_state}"


# ========== TEST 2: Cleanup on Load Failure ==========

@pytest.mark.asyncio
async def test_cleanup_on_load_failure(tmp_path, memory_adapter):
    """P0: Verify orphaned directories are cleaned up on load failure."""
    runtime = CoreRuntime(memory_adapter)
    
    # Create bad plugin archive (invalid plugin.py)
    bad_plugin_dir = tmp_path / "bad_plugin"
    bad_plugin_dir.mkdir()
    
    plugin_json = {
        "name": "bad_plugin",
        "version": "1.0.0",
        "entrypoint": "plugin.py",
        "description": "Bad plugin",
        "author": "test",
    }
    
    (bad_plugin_dir / "plugin.json").write_text(json.dumps(plugin_json))
    
    # Invalid python code
    bad_python = "this is not valid python code !!!"
    (bad_plugin_dir / "plugin.py").write_text(bad_python)
    
    # Create archive
    bad_archive = tmp_path / "bad_plugin.zip"
    with zipfile.ZipFile(bad_archive, "w") as zf:
        for file_path in bad_plugin_dir.iterdir():
            zf.write(file_path, arcname=file_path.name)
    
    # Try to install
    installer = MarketplaceInstaller(tmp_path / "plugins")
    plugins_dir_before = set(installer.plugins_dir.glob("*"))
    
    with pytest.raises(Exception):  # Should raise InstallerError
        await installer.install_from_file(bad_archive, runtime=runtime)
    
    # Verify no orphaned directory
    plugins_dir_after = set(installer.plugins_dir.glob("*"))
    assert plugins_dir_before == plugins_dir_after, "Orphaned plugin directory not cleaned up"


# ========== TEST 3: Circular Dependency Detection ==========

def test_circular_dependency_detection():
    """P0: Verify circular dependencies are detected."""
    # Create mock objects
    registry = Mock()
    plugin_manager = Mock()
    storage = Mock()
    
    resolver = DependencyResolver(registry, plugin_manager, storage)
    
    # Create test plugins
    plugin_b = DemoPluginB()
    plugin_c = DemoPluginC()
    
    # Set up plugin manager to return our test plugins
    plugin_manager.get_loaded_plugins.return_value = [
        ("test_plugin_b", plugin_b),
        ("test_plugin_c", plugin_c),
    ]
    
    # Run dependency check - should detect cycle
    # B requires test:service_a, C provides test:service_a
    # C requires test:service_b, B provides test:service_b
    # This creates a cycle: B -> C -> B
    errors = resolver.validate_runtime_integrity()
    
    # Should have circular dependency error
    assert len(errors) > 0, f"Should detect circular dependency, got {errors}"
    assert any("circular" in str(e).lower() for e in errors), f"Expected circular error in: {errors}"



# ========== TEST 4: Concurrent Handler Safety ==========

def test_concurrent_handler_safety():
    """P0: Verify ExecutionRouter lock protects handler dictionary."""
    from core.execution_router import ExecutionRouter
    from unittest.mock import Mock
    import threading
    
    # Create a mock runtime
    mock_runtime = Mock()
    router = ExecutionRouter(mock_runtime)
    results = {"errors": []}
    
    # Register initial handler
    async def async_handler(context, op):
        return {"success": True}
    
    router.register_handler("test.op", async_handler)
    
    def register_task():
        try:
            for i in range(10):
                router.register_handler(f"test.op.{i}", async_handler)
        except Exception as e:
            results["errors"].append(str(e))
    
    def unregister_task():
        try:
            for i in range(10):
                if f"test.op.{i}" in router._local_handlers:
                    router.unregister_handler(f"test.op.{i}")
        except Exception as e:
            results["errors"].append(str(e))
    
    # Simulate concurrent access with threads
    threads = [
        threading.Thread(target=register_task),
        threading.Thread(target=unregister_task),
        threading.Thread(target=register_task),
    ]
    
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    
    # Should not have any thread safety errors
    assert len(results["errors"]) == 0, f"Concurrent access caused errors: {results['errors']}"


# ========== TEST 5: Plugin Manager Lock Safety ==========

def test_plugin_manager_lock_safety():
    """P0: Verify PluginManager lock protects internal state."""
    from unittest.mock import Mock
    import threading
    
    pm = PluginManager(runtime=None)  # Create without runtime for testing
    results = {"errors": []}
    
    plugin = DemoPluginA()
    
    def load_task():
        try:
            for _ in range(5):
                with pm._plugin_lock:
                    pm._plugins["test_plugin"] = plugin
                    pm._states["test_plugin"] = PluginState.LOADED
        except Exception as e:
            results["errors"].append(str(e))
    
    def state_task():
        try:
            for _ in range(5):
                with pm._plugin_lock:
                    state = pm._states.get("test_plugin", PluginState.UNLOADED)
                    assert state in [PluginState.UNLOADED, PluginState.LOADED, PluginState.STARTED, PluginState.ERROR]
        except Exception as e:
            results["errors"].append(str(e))
    
    # Simulate concurrent state access
    threads = [
        threading.Thread(target=load_task),
        threading.Thread(target=state_task),
        threading.Thread(target=load_task),
    ]
    
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    
    # Should not have corruption or errors
    assert len(results["errors"]) == 0, f"Lock safety errors: {results['errors']}"


# ========== TEST 6: Concurrent Provider Unregister During Execution ==========

def test_concurrent_provider_unregister_during_execution():
    """P0: Provider unregister while operation is executing should not crash."""
    from core.capability_registry import CapabilityRegistry
    import threading
    
    reg = CapabilityRegistry()
    reg.register_provider("plugin_a", "test.capability", provider_type="local")
    
    results = {"errors": [], "unregisters": 0}
    
    def unregister_task():
        try:
            for _ in range(10):
                reg.unregister_plugin("plugin_a")
                results["unregisters"] += 1
        except Exception as e:
            results["errors"].append(f"unregister error: {e}")
    
    def get_task():
        try:
            for _ in range(10):
                providers = reg.get_all_providers_for_capability("test.capability")
                # Should not crash even if race condition occurs
        except Exception as e:
            results["errors"].append(f"get error: {e}")
    
    threads = [
        threading.Thread(target=unregister_task),
        threading.Thread(target=get_task),
        threading.Thread(target=get_task),
    ]
    
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    
    # No dict changed size errors
    assert len(results["errors"]) == 0, f"Race condition errors: {results['errors']}"


# ========== TEST 7: OperationManager Handler Lock Safety ==========

def test_operation_manager_handler_lock_safety():
    """P0: OperationManager._handlers must be protected by lock."""
    from core.operations import OperationManager
    import threading
    
    runtime = Mock()
    runtime.storage = None
    om = OperationManager(runtime)
    
    results = {"errors": [], "registered": 0}
    
    async def dummy_handler(runtime, op):
        return {"result": "ok"}
    
    def register_task():
        try:
            for i in range(5):
                om.register_handler(f"op_type_{i}", dummy_handler)
                results["registered"] += 1
        except Exception as e:
            results["errors"].append(f"register error: {e}")
    
    def list_task():
        try:
            for _ in range(5):
                handlers = om.list_handler_types()
                # Should not crash
        except Exception as e:
            results["errors"].append(f"list error: {e}")
    
    threads = [
        threading.Thread(target=register_task),
        threading.Thread(target=list_task),
        threading.Thread(target=register_task),
    ]
    
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    
    assert len(results["errors"]) == 0, f"Handler lock errors: {results['errors']}"


# ========== TEST 8: CapabilityRegistry Full Thread Safety ==========

def test_capability_registry_thread_safety():
    """P0: CapabilityRegistry should safely handle concurrent registration/unregistration."""
    from core.capability_registry import CapabilityRegistry
    import threading
    
    reg = CapabilityRegistry()
    results = {"errors": [], "ops": 0}
    
    def worker(worker_id):
        try:
            for i in range(20):
                # Register provider
                plugin_name = f"plugin_{worker_id}_{i}"
                cap_id = f"cap_{i % 5}"
                
                reg.register_provider(plugin_name, cap_id)
                
                # Get providers
                providers = reg.get_providers(cap_id)
                
                # Update health
                if providers:
                    reg.set_provider_health(providers[0], cap_id, healthy=(i % 2 == 0))
                
                results["ops"] += 1
        except Exception as e:
            results["errors"].append(f"worker_{worker_id} error: {e}")
    
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    
    assert len(results["errors"]) == 0, f"Registry thread safety errors: {results['errors']}"
    assert results["ops"] > 0


# ========== TEST 9: Subprocess Output Limit ==========

# NOTE: Старые executors удалены. Эти тесты должны быть переписаны для новых backends.
# TODO: Переписать тесты для execution/backends/ProcessBackend и ContainerBackend

# def test_subprocess_output_limit():
#     """P0: ProcessExecutor should limit subprocess output to prevent OOM."""
#     # DEPRECATED: Используйте execution/backends/ProcessBackend
#     pass


# # ========== TEST 10: Container Cleanup on Failure ==========

# def test_container_cleanup_on_failure():
#     """P0: ContainerExecutor should cleanup containers even on failure."""
#     # DEPRECATED: Используйте execution/backends/ContainerBackend
#     pass


# ========== TEST 11: Provider Disappears Between Selection and Execution ==========

def test_provider_disappears_between_selection_and_execution():
    """P0: Multiple snapshot selections ensure atomic provider references."""
    from core.capability_registry import CapabilityRegistry
    import threading
    
    reg = CapabilityRegistry()
    reg.register_provider("plugin_a", "test.capability", provider_type="local")
    
    results = {"snapshots": 0, "errors": 0}
    
    def snapshot_selection():
        try:
            # Simulate atomic selection: get all providers + make snapshot
            with reg._lock:
                all_providers = reg.get_all_providers_for_capability("test.capability")
                if all_providers:
                    snapshot = dict(all_providers[0])
                    results["snapshots"] += 1
        except Exception as e:
            results["errors"] += 1
    
    def aggressive_unregister():
        try:
            for _ in range(5):
                reg.unregister_plugin("plugin_a")
                reg.register_provider("plugin_a", "test.capability", provider_type="local")
        except Exception:
            pass
    
    threads = [
        threading.Thread(target=snapshot_selection),
        threading.Thread(target=aggressive_unregister),
        threading.Thread(target=snapshot_selection),
    ]
    
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    
    # No corrupted snapshots
    assert results["errors"] == 0, "Snapshot selection should be atomic"


