"""
Tests for marketplace module.

Tests:
- Valid plugin installation
- Archive validation (bad ZIP)
- Duplicate installation detection
- SHA256 validation
- Capability registration
- Plugin removal
- Update operations
- Enable/disable
- List installed
- Storage integration
"""

import pytest
import asyncio
import tempfile
import zipfile
import json
import hashlib
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch

from modules.plugins.schema import validate_plugin_json
from modules.marketplace.installer import MarketplaceInstaller, InstallerError
from modules.marketplace.services import MarketplaceService
from modules.marketplace.module import MarketplaceModule
from core.operations import Operation, OperationInitiator, OperationInitiatorKind


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def temp_dir():
    """Create temporary directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def plugins_dir(temp_dir):
    """Create plugins directory."""
    plugins_path = temp_dir / "plugins"
    plugins_path.mkdir()
    return plugins_path


@pytest.fixture
def installer(plugins_dir):
    """Create marketplace installer."""
    return MarketplaceInstaller(plugins_dir)


@pytest.fixture
def mock_runtime(temp_dir):
    """Create mock runtime."""
    runtime = Mock()
    runtime.config = {"plugins_dir": str(temp_dir / "plugins")}
    runtime.storage = Mock()
    runtime.storage.get = Mock(return_value={})
    runtime.storage.get_sync = Mock(return_value={})
    runtime.storage.set = Mock()
    runtime.plugin_manager = AsyncMock()
    runtime.operations = AsyncMock()
    runtime.capabilities = AsyncMock()
    # Prevent auto-create of context (so module uses storage directly)
    runtime.create_context = Mock(return_value=None)
    return runtime


@pytest.fixture
def test_plugin_archive(temp_dir):
    """Create a test plugin archive."""
    plugin_dir = temp_dir / "test_plugin_src"
    plugin_dir.mkdir()
    
    # Create plugin.json
    plugin_json = {
        "name": "test_plugin",
        "version": "1.0.0",
        "description": "Test plugin",
        "author": "test",
        "entrypoint": "plugin.py",
        "capabilities_provided": ["test.capability"],
    }
    (plugin_dir / "plugin.json").write_text(json.dumps(plugin_json))
    
    # Create __init__.py
    (plugin_dir / "__init__.py").write_text("")
    
    # Create plugin.py with BasePlugin subclass
    plugin_py = '''
from core.kernel.base_plugin import BasePlugin

class TestPlugin(BasePlugin):
    def metadata(self):
        return {
            "name": "test_plugin",
            "version": "1.0.0"
        }
    
    async def on_load(self):
        pass
    
    async def on_start(self):
        pass
    
    async def on_stop(self):
        pass
    
    def list_capabilities(self):
        return []
'''
    (plugin_dir / "plugin.py").write_text(plugin_py)
    
    # Create ZIP archive
    archive_path = temp_dir / "test_plugin.zip"
    with zipfile.ZipFile(archive_path, "w") as zf:
        for file_path in plugin_dir.iterdir():
            zf.write(file_path, arcname=file_path.name)
    
    return archive_path


def calculate_sha256(path):
    """Calculate file SHA256."""
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        sha256.update(f.read())
    return sha256.hexdigest()


# ============================================================================
# Test MarketplaceInstaller
# ============================================================================

class TestMarketplaceInstaller:
    """Tests for MarketplaceInstaller."""
    
    @pytest.mark.asyncio
    async def test_install_valid_plugin(self, installer, test_plugin_archive, mock_runtime):
        """Test installing a valid plugin."""
        # Mock plugin manager
        mock_runtime.plugin_manager.load_plugin = AsyncMock()
        
        result = await installer.install_from_file(
            str(test_plugin_archive),
            runtime=mock_runtime
        )
        
        assert result["name"] == "test_plugin"
        assert result["version"] == "1.0.0"
        assert "installed_at" in result
        assert "hash" in result
        assert result["entrypoint"] == "plugin.py"
        assert "test.capability" in result["capabilities_provided"]
    
    @pytest.mark.asyncio
    async def test_install_nonexistent_archive(self, installer):
        """Test installing from non-existent archive."""
        with pytest.raises(InstallerError, match="Archive not found"):
            await installer.install_from_file("/nonexistent/plugin.zip")
    
    @pytest.mark.asyncio
    async def test_install_unsupported_format(self, temp_dir):
        """Test installing unsupported archive format."""
        installer = MarketplaceInstaller(temp_dir / "plugins")
        bad_archive = temp_dir / "plugin.txt"
        bad_archive.write_text("not an archive")
        
        with pytest.raises(InstallerError, match="Unsupported archive format"):
            await installer.install_from_file(str(bad_archive))
    
    @pytest.mark.asyncio
    async def test_install_sha256_validation(self, installer, test_plugin_archive):
        """Test SHA256 validation."""
        wrong_sha256 = "0000000000000000000000000000000000000000000000000000000000000000"
        
        with pytest.raises(InstallerError, match="SHA256 mismatch"):
            await installer.install_from_file(
                str(test_plugin_archive),
                sha256=wrong_sha256
            )
    
    @pytest.mark.asyncio
    async def test_install_sha256_success(self, installer, test_plugin_archive, mock_runtime):
        """Test SHA256 validation succeeds with correct hash."""
        mock_runtime.plugin_manager.load_plugin = AsyncMock()
        
        correct_sha256 = calculate_sha256(test_plugin_archive)
        result = await installer.install_from_file(
            str(test_plugin_archive),
            sha256=correct_sha256,
            runtime=mock_runtime
        )
        
        assert result["hash"] == correct_sha256
    
    @pytest.mark.asyncio
    async def test_install_bad_zip(self, temp_dir, installer):
        """Test installing corrupted ZIP."""
        bad_zip = temp_dir / "bad.zip"
        bad_zip.write_text("not a real zip file")
        
        with pytest.raises(InstallerError, match="Invalid archive"):
            await installer.install_from_file(str(bad_zip))
    
    @pytest.mark.asyncio
    async def test_install_missing_plugin_json(self, temp_dir, installer):
        """Test installing plugin without plugin.json."""
        # Create ZIP without plugin.json
        archive_path = temp_dir / "no_manifest.zip"
        with zipfile.ZipFile(archive_path, "w") as zf:
            zf.writestr("plugin.py", "# empty")
        
        with pytest.raises(InstallerError, match="plugin.json not found"):
            await installer.install_from_file(str(archive_path))

    @pytest.mark.asyncio
    async def test_install_rejects_zip_slip_archive(self, temp_dir, installer):
        """Архив не должен писать файлы вне target_dir."""
        archive_path = temp_dir / "zip_slip.zip"
        with zipfile.ZipFile(archive_path, "w") as zf:
            zf.writestr("../escape.txt", "owned")
            zf.writestr("plugin.json", json.dumps({
                "name": "test_plugin",
                "version": "1.0.0",
                "description": "Test plugin",
                "author": "test",
                "entrypoint": "plugin.py",
            }))
            zf.writestr("plugin.py", "from core.base_plugin import BasePlugin\nclass TestPlugin(BasePlugin): pass\n")

        with pytest.raises(InstallerError, match="Unsafe archive path|escapes target directory"):
            await installer.install_from_file(str(archive_path))
    
    @pytest.mark.asyncio
    async def test_install_invalid_manifest(self, temp_dir, installer):
        """Test installing plugin with invalid plugin.json."""
        # Create ZIP with invalid manifest
        archive_path = temp_dir / "invalid_manifest.zip"
        with zipfile.ZipFile(archive_path, "w") as zf:
            # Missing required fields
            zf.writestr("plugin.json", json.dumps({"name": "test"}))
        
        with pytest.raises(InstallerError, match="Invalid plugin.json"):
            await installer.install_from_file(str(archive_path))
    
    @pytest.mark.asyncio
    async def test_install_duplicate_plugin(self, installer, test_plugin_archive, mock_runtime):
        """Test duplicate plugin detection."""
        mock_runtime.plugin_manager.load_plugin = AsyncMock()
        
        # Install first time
        await installer.install_from_file(str(test_plugin_archive), runtime=mock_runtime)
        
        # Try to install again
        with pytest.raises(InstallerError, match="already installed"):
            await installer.install_from_file(str(test_plugin_archive), runtime=mock_runtime)
    
    @pytest.mark.asyncio
    async def test_uninstall_plugin(self, installer, test_plugin_archive, mock_runtime):
        """Test uninstalling a plugin."""
        mock_runtime.plugin_manager.load_plugin = AsyncMock()
        mock_runtime.plugin_manager.stop_plugin = AsyncMock()
        mock_runtime.plugin_manager.unload_plugin = AsyncMock()
        
        # Install first
        await installer.install_from_file(str(test_plugin_archive), runtime=mock_runtime)
        
        # Uninstall
        result = await installer.uninstall("test_plugin", runtime=mock_runtime)
        
        assert result["name"] == "test_plugin"
        assert "uninstalled_at" in result
    
    @pytest.mark.asyncio
    async def test_uninstall_nonexistent_plugin(self, installer):
        """Test uninstalling non-existent plugin."""
        with pytest.raises(InstallerError, match="Plugin not found"):
            await installer.uninstall("nonexistent")


# ============================================================================
# Test MarketplaceService
# ============================================================================

class TestMarketplaceService:
    """Tests for MarketplaceService."""
    
    def test_service_initialization(self, mock_runtime):
        """Test service initialization."""
        service = MarketplaceService(mock_runtime)
        
        assert service.runtime == mock_runtime
        assert service.storage == mock_runtime.storage
        assert service.plugin_manager == mock_runtime.plugin_manager
        assert isinstance(service.installer, MarketplaceInstaller)
    
    @pytest.mark.asyncio
    async def test_handle_install_success(self, installer, test_plugin_archive, mock_runtime):
        """Test handle_install operation."""
        mock_runtime.plugin_manager.load_plugin = AsyncMock()
        service = MarketplaceService(mock_runtime)
        
        operation = Operation(
            operation_id="test_op",
            op_type="marketplace.install",
            params={
                "archive_path": str(test_plugin_archive),
            },
            initiator=OperationInitiator(kind=OperationInitiatorKind.ADMIN)
        )
        
        result = await service.handle_install(operation)
        
        assert result["status"] == "success"
        assert result["data"]["name"] == "test_plugin"
        assert result["data"]["version"] == "1.0.0"
    
    @pytest.mark.asyncio
    async def test_handle_install_missing_archive_path(self, mock_runtime):
        """Test handle_install with missing archive_path."""
        service = MarketplaceService(mock_runtime)
        
        operation = Operation(
            operation_id="test_op",
            op_type="marketplace.install",
            params={},
            initiator=OperationInitiator(kind=OperationInitiatorKind.ADMIN)
        )
        
        result = await service.handle_install(operation)
        
        assert result["status"] == "failure"
        assert "archive_path required" in result["error"]
    
    @pytest.mark.asyncio
    async def test_handle_remove_success(self, installer, test_plugin_archive, mock_runtime):
        """Test handle_remove operation."""
        mock_runtime.plugin_manager.load_plugin = AsyncMock()
        mock_runtime.plugin_manager.stop_plugin = AsyncMock()
        mock_runtime.plugin_manager.unload_plugin = AsyncMock()
        
        service = MarketplaceService(mock_runtime)
        
        # Install first
        await installer.install_from_file(str(test_plugin_archive), runtime=mock_runtime)
        mock_runtime.storage.get = Mock(return_value={
            "test_plugin": {"name": "test_plugin", "version": "1.0.0"}
        })
        
        # Remove
        operation = Operation(
            operation_id="test_op",
            op_type="marketplace.remove",
            params={"plugin_name": "test_plugin"},
            initiator=OperationInitiator(kind=OperationInitiatorKind.ADMIN)
        )
        
        result = await service.handle_remove(operation)
        
        assert result["status"] == "success"
        assert result["data"]["name"] == "test_plugin"
    
    @pytest.mark.asyncio
    async def test_handle_remove_nonexistent_plugin(self, mock_runtime):
        """Test handle_remove with non-existent plugin."""
        mock_runtime.storage.get = Mock(return_value={})
        service = MarketplaceService(mock_runtime)
        
        operation = Operation(
            operation_id="test_op",
            op_type="marketplace.remove",
            params={"plugin_name": "nonexistent"},
            initiator=OperationInitiator(kind=OperationInitiatorKind.ADMIN)
        )
        
        result = await service.handle_remove(operation)
        
        assert result["status"] == "failure"
        assert "not installed" in result["error"]

    @pytest.mark.asyncio
    async def test_install_from_url_requires_signature_metadata(self, temp_dir):
        """Registry install must require signature/public_key metadata."""
        installer = MarketplaceInstaller(temp_dir / "plugins")

        with pytest.raises(InstallerError, match="requires signature and public_key"):
            await installer.install_from_url(
                "https://example.com/plugin.zip",
                sha256="abc",
                signature=None,
                public_key=None,
                runtime=None,
            )
    
    @pytest.mark.asyncio
    async def test_handle_list_installed(self, mock_runtime):
        """Test handle_list_installed operation."""
        installed_plugins = {
            "plugin1": {"name": "plugin1", "version": "1.0.0"},
            "plugin2": {"name": "plugin2", "version": "2.0.0"},
        }
        mock_runtime.storage.get = Mock(return_value=installed_plugins)
        
        service = MarketplaceService(mock_runtime)
        
        operation = Operation(
            operation_id="test_op",
            op_type="marketplace.list_installed",
            params={},
            initiator=OperationInitiator(kind=OperationInitiatorKind.ADMIN)
        )
        
        result = await service.handle_list_installed(operation)
        
        assert result["status"] == "success"
        assert result["data"]["count"] == 2
        assert "plugin1" in result["data"]["installed_plugins"]
        assert "plugin2" in result["data"]["installed_plugins"]


# ============================================================================
# Test MarketplaceModule
# ============================================================================

class TestMarketplaceModule:
    """Tests for MarketplaceModule."""
    
    def test_module_initialization(self, mock_runtime):
        """Test module initialization."""
        module = MarketplaceModule(mock_runtime)
        
        assert module.name == "marketplace"
        assert module.version == "1.0.0"
        assert isinstance(module.service, MarketplaceService)
    
    def test_list_capabilities(self, mock_runtime):
        """Test capability listing."""
        module = MarketplaceModule(mock_runtime)
        caps = module.list_capabilities()
        
        assert len(caps) == 11
        cap_names = [cap["name"] for cap in caps]
        
        assert "marketplace.install" in cap_names
        assert "marketplace.remove" in cap_names
        assert "marketplace.update" in cap_names
        assert "marketplace.enable" in cap_names
        assert "marketplace.disable" in cap_names
        assert "marketplace.list_installed" in cap_names
    
    def test_list_installed_plugins(self, mock_runtime):
        """Test listing installed plugins."""
        installed = {
            "test_plugin": {"name": "test_plugin", "version": "1.0.0"},
        }
        mock_runtime.storage.get = Mock(return_value=installed)
        mock_runtime.storage.get_sync = Mock(return_value=installed)
        
        module = MarketplaceModule(mock_runtime)
        result = module.list_installed_plugins()
        
        assert "test_plugin" in result
        assert result["test_plugin"]["version"] == "1.0.0"
    
    def test_get_manifest(self, mock_runtime):
        """Test getting plugin manifest."""
        plugin_manifest = {
            "name": "test_plugin",
            "version": "1.0.0",
            "description": "Test",
        }
        installed = {"test_plugin": plugin_manifest}
        mock_runtime.storage.get = Mock(return_value=installed)
        mock_runtime.storage.get_sync = Mock(return_value=installed)
        
        module = MarketplaceModule(mock_runtime)
        manifest = module.get_manifest("test_plugin")
        
        assert manifest is not None
        assert manifest["name"] == "test_plugin"
    
    def test_get_manifest_not_found(self, mock_runtime):
        """Test getting non-existent manifest."""
        mock_runtime.storage.get = Mock(return_value={})
        mock_runtime.storage.get_sync = Mock(return_value={})
        
        module = MarketplaceModule(mock_runtime)
        manifest = module.get_manifest("nonexistent")
        
        assert manifest is None
    
    @pytest.mark.asyncio
    async def test_on_start_registers_operations(self, mock_runtime):
        """Test register() registers operations."""
        # Make register_handler a regular mock (not async)
        mock_runtime.operations = Mock()
        mock_runtime.operations.register_handler = Mock()
        
        module = MarketplaceModule(mock_runtime)
        
        await module.register()
        
        # Verify operations registered
        assert mock_runtime.operations.register_handler.call_count == 11
    
    @pytest.mark.asyncio
    async def test_health_check(self, mock_runtime):
        """Test health check."""
        installed = {
            "plugin1": {"name": "plugin1"},
            "plugin2": {"name": "plugin2"},
        }
        mock_runtime.storage.get = Mock(return_value=installed)
        mock_runtime.storage.get_sync = Mock(return_value=installed)
        
        module = MarketplaceModule(mock_runtime)
        health = await module.health_check()
        
        assert health["status"] == "healthy"
        assert health["installed_plugins_count"] == 2
        assert len(health["operations_available"]) == 11


# ============================================================================
# Integration Tests
# ============================================================================

class TestMarketplaceIntegration:
    """Integration tests for marketplace components."""
    
    @pytest.mark.asyncio
    async def test_full_install_workflow(self, temp_dir, test_plugin_archive, mock_runtime):
        """Test complete install workflow: archive -> validation -> storage."""
        # Setup plugin directory
        plugins_dir = temp_dir / "plugins"
        plugins_dir.mkdir()
        mock_runtime.config = {"plugins_dir": str(plugins_dir)}
        mock_runtime.plugin_manager.load_plugin = AsyncMock()
        
        # Create service and install
        service = MarketplaceService(mock_runtime)
        
        operation = Operation(
            operation_id="install_op",
            op_type="marketplace.install",
            params={"archive_path": str(test_plugin_archive)},
            initiator=OperationInitiator(kind=OperationInitiatorKind.ADMIN)
        )
        
        result = await service.handle_install(operation)
        
        # Verify result
        assert result["status"] == "success"
        assert result["data"]["name"] == "test_plugin"
        assert (plugins_dir / "test_plugin").exists()
        
        # Verify storage was updated
        mock_runtime.storage.set.assert_called()
    
    @pytest.mark.asyncio
    async def test_install_then_uninstall(self, temp_dir, test_plugin_archive, mock_runtime):
        """Test install followed by uninstall."""
        plugins_dir = temp_dir / "plugins"
        plugins_dir.mkdir()
        mock_runtime.config = {"plugins_dir": str(plugins_dir)}
        mock_runtime.plugin_manager.load_plugin = AsyncMock()
        mock_runtime.plugin_manager.stop_plugin = AsyncMock()
        mock_runtime.plugin_manager.unload_plugin = AsyncMock()
        
        service = MarketplaceService(mock_runtime)
        
        # Install
        install_op = Operation(
            operation_id="install_op",
            op_type="marketplace.install",
            params={"archive_path": str(test_plugin_archive)},
            initiator=OperationInitiator(kind=OperationInitiatorKind.ADMIN)
        )
        
        result = await service.handle_install(install_op)
        assert result["status"] == "success"
        
        # Setup for removal
        mock_runtime.storage.get = Mock(return_value={
            "test_plugin": {"name": "test_plugin", "version": "1.0.0"}
        })
        
        # Uninstall
        remove_op = Operation(
            operation_id="remove_op",
            op_type="marketplace.remove",
            params={"plugin_name": "test_plugin"},
            initiator=OperationInitiator(kind=OperationInitiatorKind.ADMIN)
        )
        
        result = await service.handle_remove(remove_op)
        assert result["status"] == "success"
        assert not (plugins_dir / "test_plugin").exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
