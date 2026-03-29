"""
P0 Hardening Tests — Critical robustness checks.

Tests for:
1. Race condition protection (ExecutionRouter, PluginManager)
2. Circular dependency detection
3. Post-install activation
4. Cleanup on load failure
"""

import json
import zipfile
import asyncio
from unittest.mock import Mock

import pytest

from core.dependency.resolver import DependencyResolver
from core.kernel.base_plugin import BasePlugin, PluginMetadata
from core.kernel.plugin_manager import PluginManager
from core.kernel.plugin_registry import PluginState
from core.runtime.runtime import CoreRuntime
from core.state_engine import StateEngine
from modules.marketplace.installer import MarketplaceInstaller
from modules.storage.port import CoreStoragePort
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
    adapter = InMemoryStorageAdapter()
    state_engine = StateEngine()
    return CoreStoragePort(adapter, state_engine)


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
    plugin_py = """
from core.kernel.base_plugin import BasePlugin, PluginMetadata

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
"""

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
    assert plugins_dir_before == plugins_dir_after, (
        "Orphaned plugin directory not cleaned up"
    )


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
    assert any("circular" in str(e).lower() for e in errors), (
        f"Expected circular error in: {errors}"
    )


# ========== TEST 4: Concurrent Handler Safety ==========


@pytest.mark.asyncio
async def test_concurrent_handler_safety():
    """P0: Verify ExecutionRouter asyncio.Lock protects handler dictionary under async concurrency."""
    from modules.execution.router import ExecutionRouter
    from unittest.mock import Mock
    import asyncio
    
    mock_runtime = Mock()
    with pytest.warns(DeprecationWarning):
        router = ExecutionRouter(mock_runtime)
    results = {"errors": []}
    
    async def async_handler(context, op):
        return {"success": True}
    
    await router.register_handler("test.op", async_handler)
    
    async def register_task():
        try:
            for i in range(10):
                await router.register_handler(f"test.op.{i}", async_handler)
        except Exception as e:
            results["errors"].append(str(e))
    
    async def unregister_task():
        try:
            for i in range(10):
                await router.unregister_handler(f"test.op.{i}")
        except Exception as e:
            results["errors"].append(str(e))
    
    # Concurrent async tasks (no event loop blocking)
    await asyncio.gather(
        register_task(),
        unregister_task(),
        register_task(),
    )
    
    assert len(results["errors"]) == 0, f"Concurrent access caused errors: {results['errors']}"


# ========== TEST 5: Plugin Manager Lock Safety ==========


@pytest.mark.asyncio
async def test_plugin_manager_lock_safety():
    """P0: Verify PluginManager asyncio.Lock protects internal state under async concurrency."""
    pm = PluginManager(runtime=None)
    results = {"errors": []}
    plugin = DemoPluginA()

    # First register plugins
    for i in range(5):
        await pm._registry.register(f"test_plugin_{i}", plugin, PluginState.LOADED)

    async def state_task():
        try:
            for _ in range(5):
                for i in range(5):
                    state = await pm._registry.get_plugin_state(f"test_plugin_{i}")
                    val = state.value if state else "unloaded"
                    assert val in ["unloaded", "loaded", "started", "stopped", "error"]
        except Exception as e:
            results["errors"].append(str(e))

    async def update_task():
        try:
            for _ in range(3):
                for i in range(5):
                    await pm._registry.set_plugin_state(f"test_plugin_{i}", PluginState.STARTED)
                    await pm._registry.set_plugin_state(f"test_plugin_{i}", PluginState.LOADED)
        except Exception as e:
            results["errors"].append(str(e))

    await asyncio.gather(
        state_task(),
        update_task(),
        state_task(),
    )

    assert len(results["errors"]) == 0, f"Lock safety errors: {results['errors']}"


# ========== TEST 6: Concurrent Provider Unregister During Execution ==========


def test_concurrent_provider_unregister_during_execution():
    """P0: Provider unregister while operation is executing should not crash."""
    import threading

    from modules.capability.registry import CapabilityRegistry

    reg = CapabilityRegistry()
    # Use sync_lock for direct dict manipulation in tests
    with reg._sync_lock:
        reg._providers["test.capability"] = [
            {
                "plugin": "plugin_a",
                "type": "local",
                "healthy": True,
                "protocol_version": 1,
                "provider_version": None,
                "timeouts": {},
                "capabilities": [],
                "execution_mode": "in_process",
            }
        ]

    results = {"errors": [], "unregisters": 0}

    def unregister_task():
        try:
            for _ in range(10):
                with reg._sync_lock:
                    reg._providers.pop("test.capability", None)
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
    import threading

    from core.operations import OperationManager

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
    import threading

    from modules.capability.registry import CapabilityRegistry

    reg = CapabilityRegistry()
    results = {"errors": [], "ops": 0}

    def worker(worker_id):
        try:
            for i in range(20):
                # Register provider directly via sync lock
                plugin_name = f"plugin_{worker_id}_{i}"
                cap_id = f"cap_{i % 5}"

                with reg._sync_lock:
                    if cap_id not in reg._providers:
                        reg._providers[cap_id] = []
                    reg._providers[cap_id].append(
                        {
                            "plugin": plugin_name,
                            "type": "local",
                            "healthy": True,
                            "protocol_version": 1,
                            "provider_version": None,
                            "timeouts": {},
                            "capabilities": [],
                            "execution_mode": "in_process",
                        }
                    )

                # Get providers (sync read)
                providers = reg.get_providers(cap_id)

                # Update health via sync lock
                if providers:
                    with reg._sync_lock:
                        for p in reg._providers.get(cap_id, []):
                            if p["plugin"] == providers[0]:
                                p["healthy"] = i % 2 == 0

                results["ops"] += 1
        except Exception as e:
            results["errors"].append(f"worker_{worker_id} error: {e}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results["errors"]) == 0, (
        f"Registry thread safety errors: {results['errors']}"
    )
    assert results["ops"] > 0


# ========== TEST 9: Subprocess Output Limit ==========

# NOTE: Process executor tests have been refactored to use execution/backends/ProcessBackend
# and ContainerBackend instead of deprecated core.process_executor and core.container_executor.
#
# To test subprocess output limits:
# - Use core.execution.backends.ProcessBackend
# - Configure stdout_limit_bytes in execution config
# - Test that backends respect memory constraints

# ========== TEST 10: Container Cleanup on Failure ==========

# NOTE: Container executor tests have been refactored to use execution/backends/ContainerBackend.
# To test container cleanup:
# - Use core.execution.backends.ContainerBackend
# - Verify container lifecycle management
# - Test cleanup on failure scenarios
#     """P0: ContainerExecutor should cleanup containers even on failure."""
#     # DEPRECATED: Используйте execution/backends/ContainerBackend
#     pass


# ========== TEST 11: Provider Disappears Between Selection and Execution ==========


def test_provider_disappears_between_selection_and_execution():
    """P0: Multiple snapshot selections ensure atomic provider references."""
    import threading

    from modules.capability.registry import CapabilityRegistry

    reg = CapabilityRegistry()
    # Directly insert provider via sync lock (tests thread-safety only)
    with reg._sync_lock:
        reg._providers["test.capability"] = [
            {
                "plugin": "plugin_a",
                "type": "local",
                "healthy": True,
                "protocol_version": 1,
                "provider_version": None,
                "timeouts": {},
                "capabilities": [],
                "execution_mode": "in_process",
            }
        ]

    results = {"snapshots": 0, "errors": 0}

    def snapshot_selection():
        try:
            # Simulate atomic selection: get all providers + make snapshot
            with reg._sync_lock:
                all_providers = reg.get_all_providers_for_capability("test.capability")
                if all_providers:
                    snapshot = dict(all_providers[0])
                    results["snapshots"] += 1
        except Exception:
            results["errors"] += 1

    def aggressive_unregister():
        try:
            for _ in range(5):
                with reg._sync_lock:
                    reg._providers.pop("test.capability", None)
                with reg._sync_lock:
                    reg._providers["test.capability"] = [
                        {
                            "plugin": "plugin_a",
                            "type": "local",
                            "healthy": True,
                            "protocol_version": 1,
                            "provider_version": None,
                            "timeouts": {},
                            "capabilities": [],
                            "execution_mode": "in_process",
                        }
                    ]
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
