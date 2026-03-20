"""
Comprehensive tests for Storage v3 dual-mode architecture.

Test Coverage:
- Single mode (backward compatibility)
- Dual mode initialization with separate adapters
- Namespace enforcement (vault namespaces cannot go through core storage)
- Auto-routing (vault namespaces go to vault storage)
- Explicit routing (target="core" or target="vault")
- Vault namespace listing and isolation
- Error handling (configuration, namespace violations)
- Migration from single to dual mode
"""

import os
import tempfile

import pytest

from core.adapters.sqlite_adapter import SQLiteAdapter
from core.adapters.storage_factory import (
    create_storage_manager,
)
from core.config import Config
from modules.storage.errors import (
    NamespaceViolationError,
    StorageConfigurationError,
)
from modules.storage.manager import StorageManager
from modules.storage.migrate import migrate_to_dual_mode


class TestStorageManagerInitialization:
    """Test StorageManager initialization in single and dual modes."""

    @pytest.mark.asyncio
    async def test_single_mode_initialization(self):
        """Test single-mode initialization (backward compatible)."""
        # Create temporary database
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            # Create core storage
            core_storage = SQLiteAdapter(db_path)
            await core_storage.initialize_schema()

            # Initialize manager in single mode
            manager = StorageManager(
                core_storage=core_storage, vault_storage=None, mode="single"
            )

            # Verify
            assert manager.mode == "single"
            assert not manager.is_dual_mode
            assert manager.get_core() is core_storage
            assert manager.get_vault() is core_storage  # Returns core in single mode

            await manager.close()

        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    @pytest.mark.asyncio
    async def test_dual_mode_initialization(self):
        """Test dual-mode initialization with separate adapters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            core_path = os.path.join(tmpdir, "core.db")
            vault_path = os.path.join(tmpdir, "vault.db")

            # Create adapters
            core_storage = SQLiteAdapter(core_path)
            await core_storage.initialize_schema()

            vault_storage = SQLiteAdapter(vault_path)
            await vault_storage.initialize_schema()

            # Initialize manager in dual mode
            manager = StorageManager(
                core_storage=core_storage, vault_storage=vault_storage, mode="dual"
            )

            # Verify
            assert manager.mode == "dual"
            assert manager.is_dual_mode
            assert manager.get_core() is core_storage
            assert manager.get_vault() is vault_storage

            await manager.close()

    def test_dual_mode_requires_vault_storage(self):
        """Test that dual mode raises error if vault_storage is None."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            core_storage = SQLiteAdapter(db_path)

            with pytest.raises(StorageConfigurationError):
                StorageManager(
                    core_storage=core_storage, vault_storage=None, mode="dual"
                )

        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_invalid_mode_raises_error(self):
        """Test that invalid mode raises error."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            core_storage = SQLiteAdapter(db_path)

            with pytest.raises(StorageConfigurationError):
                StorageManager(
                    core_storage=core_storage, vault_storage=None, mode="invalid"
                )

        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)


class TestNamespaceEnforcement:
    """Test namespace enforcement in dual mode."""

    @pytest.mark.asyncio
    async def test_vault_namespace_write_through_core_raises_error(self):
        """Test that writing vault namespace through core storage raises error in dual mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            core_path = os.path.join(tmpdir, "core.db")
            vault_path = os.path.join(tmpdir, "vault.db")

            core_storage = SQLiteAdapter(core_path)
            await core_storage.initialize_schema()
            vault_storage = SQLiteAdapter(vault_path)
            await vault_storage.initialize_schema()

            manager = StorageManager(
                core_storage=core_storage, vault_storage=vault_storage, mode="dual"
            )

            # Try to write vault namespace through core storage
            with pytest.raises(NamespaceViolationError):
                await manager.set(
                    "secrets.store",  # Critical vault namespace
                    "api_key",
                    {"value": "secret"},
                    target="core",
                )

            await manager.close()

    @pytest.mark.asyncio
    async def test_vault_namespace_auto_routing_to_vault(self):
        """Test that vault namespaces auto-route to vault storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            core_path = os.path.join(tmpdir, "core.db")
            vault_path = os.path.join(tmpdir, "vault.db")

            core_storage = SQLiteAdapter(core_path)
            await core_storage.initialize_schema()
            vault_storage = SQLiteAdapter(vault_path)
            await vault_storage.initialize_schema()

            manager = StorageManager(
                core_storage=core_storage, vault_storage=vault_storage, mode="dual"
            )

            # Write to vault namespace (should auto-route to vault)
            value = {"api_key": "secret123"}
            await manager.set("secrets.store", "db_password", value)

            # Verify in vault storage
            vault_value = await vault_storage.get("secrets.store", "db_password")
            assert vault_value == value

            # Verify NOT in core storage
            core_value = await core_storage.get("secrets.store", "db_password")
            assert core_value is None

            await manager.close()

    @pytest.mark.asyncio
    async def test_core_namespace_auto_routing_to_core(self):
        """Test that non-vault namespaces auto-route to core storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            core_path = os.path.join(tmpdir, "core.db")
            vault_path = os.path.join(tmpdir, "vault.db")

            core_storage = SQLiteAdapter(core_path)
            await core_storage.initialize_schema()
            vault_storage = SQLiteAdapter(vault_path)
            await vault_storage.initialize_schema()

            manager = StorageManager(
                core_storage=core_storage, vault_storage=vault_storage, mode="dual"
            )

            # Write to core namespace
            value = {"setting": "value"}
            await manager.set("app.config", "feature_flags", value)

            # Verify in core storage
            core_value = await core_storage.get("app.config", "feature_flags")
            assert core_value == value

            # Verify NOT in vault storage
            vault_value = await vault_storage.get("app.config", "feature_flags")
            assert vault_value is None

            await manager.close()

    @pytest.mark.asyncio
    async def test_explicit_vault_target_in_dual_mode(self):
        """Test explicit target='vault' routing in dual mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            core_path = os.path.join(tmpdir, "core.db")
            vault_path = os.path.join(tmpdir, "vault.db")

            core_storage = SQLiteAdapter(core_path)
            await core_storage.initialize_schema()
            vault_storage = SQLiteAdapter(vault_path)
            await vault_storage.initialize_schema()

            manager = StorageManager(
                core_storage=core_storage, vault_storage=vault_storage, mode="dual"
            )

            # Explicit vault routing
            value = {"token": "abc123"}
            await manager.set("oauth.tokens", "github", value, target="vault")

            vault_value = await vault_storage.get("oauth.tokens", "github")
            assert vault_value == value

            await manager.close()

    @pytest.mark.asyncio
    async def test_vault_target_in_single_mode_raises_error(self):
        """Test that target='vault' raises error in single mode."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            core_storage = SQLiteAdapter(db_path)
            await core_storage.initialize_schema()

            manager = StorageManager(
                core_storage=core_storage, vault_storage=None, mode="single"
            )

            # target='vault' should raise error in single mode
            with pytest.raises(StorageConfigurationError):
                await manager.set(
                    "oauth.tokens", "github", {"token": "x"}, target="vault"
                )

            await manager.close()

        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)


class TestStorageFactory:
    """Test storage factory dual-mode creation."""

    @pytest.mark.asyncio
    async def test_create_storage_manager_single_mode(self):
        """Test factory creates single-mode manager correctly."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            config = Config(
                storage_mode="single",
                storage_type="sqlite",
                db_path=db_path,
            )

            manager = await create_storage_manager(config)

            assert manager.is_dual_mode is False
            assert manager.get_core() is not None

            await manager.close()

        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    @pytest.mark.asyncio
    async def test_create_storage_manager_dual_mode(self):
        """Test factory creates dual-mode manager correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            core_path = os.path.join(tmpdir, "core.db")
            vault_path = os.path.join(tmpdir, "vault.db")

            config = Config(
                storage_mode="dual",
                storage_type="sqlite",
                db_path=core_path,
                vault_storage_type="sqlite",
                vault_db_path=vault_path,
            )

            manager = await create_storage_manager(config)

            assert manager.is_dual_mode is True
            assert manager.get_core() is not None
            assert manager.get_vault() is not None
            assert manager.get_core() is not manager.get_vault()

            await manager.close()


class TestMigration:
    """Test migration from single to dual mode."""

    @pytest.mark.asyncio
    async def test_migrate_vault_records_to_dual_mode(self):
        """Test migration moves vault records from core to vault storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            core_path = os.path.join(tmpdir, "core.db")
            vault_path = os.path.join(tmpdir, "vault.db")

            # Create single-mode storage with vault data
            core_storage = SQLiteAdapter(core_path)
            await core_storage.initialize_schema()

            # Pre-populate core storage with vault records
            await core_storage.set("secrets.store", "api_key", {"key": "secret123"})
            await core_storage.set("oauth.tokens", "github", {"token": "ghp_xxx"})
            await core_storage.set("app.config", "feature", {"enabled": True})

            # Verify data in core
            assert await core_storage.get("secrets.store", "api_key") is not None
            assert await core_storage.get("oauth.tokens", "github") is not None
            assert await core_storage.get("app.config", "feature") is not None

            # Create config for dual mode
            config = Config(
                storage_mode="dual",
                storage_type="sqlite",
                db_path=core_path,
                vault_storage_type="sqlite",
                vault_db_path=vault_path,
            )

            # Run migration
            migrated = await migrate_to_dual_mode(config)

            # Verify vault records moved
            assert migrated == 2  # secrets.store and oauth.tokens

            # Verify in vault storage
            vault_storage = SQLiteAdapter(vault_path)
            await vault_storage.initialize_schema()

            vault_api_key = await vault_storage.get("secrets.store", "api_key")
            assert vault_api_key == {"key": "secret123"}

            vault_token = await vault_storage.get("oauth.tokens", "github")
            assert vault_token == {"token": "ghp_xxx"}

            # Verify removed from core
            core_api_key = await core_storage.get("secrets.store", "api_key")
            assert core_api_key is None

            # Verify non-vault records stay in core
            core_feature = await core_storage.get("app.config", "feature")
            assert core_feature == {"enabled": True}

            await core_storage.close()
            await vault_storage.close()


class TestVaultNamespaceListing:
    """Test vault namespace management."""

    @pytest.mark.asyncio
    async def test_list_namespaces_in_dual_mode(self):
        """Test listing namespaces from both storages in dual mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            core_path = os.path.join(tmpdir, "core.db")
            vault_path = os.path.join(tmpdir, "vault.db")

            core_storage = SQLiteAdapter(core_path)
            await core_storage.initialize_schema()
            vault_storage = SQLiteAdapter(vault_path)
            await vault_storage.initialize_schema()

            manager = StorageManager(
                core_storage=core_storage, vault_storage=vault_storage, mode="dual"
            )

            # Add data to both
            await manager.set("app.config", "setting", {"value": "x"})
            await manager.set("secrets.store", "password", {"pwd": "secret"})

            # List namespaces
            namespaces = await manager.list_namespaces()

            assert "app.config" in namespaces
            assert "secrets.store" in namespaces

            await manager.close()

    def test_get_vault_namespaces(self):
        """Test getting critical vault namespace list."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            core_storage = SQLiteAdapter(db_path)
            manager = StorageManager(
                core_storage=core_storage, vault_storage=None, mode="single"
            )

            vault_ns = manager.get_vault_namespaces()

            assert "secrets.store" in vault_ns
            assert "oauth.tokens" in vault_ns
            assert "agent.private_keys" in vault_ns
            assert len(vault_ns) > 0

        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)


class TestConfigValidation:
    """Test Config validation for dual-mode."""

    def test_config_validation_single_mode(self):
        """Test config validation succeeds for single mode."""
        config = Config(
            storage_mode="single",
            storage_type="sqlite",
            db_path="data/runtime.db",
        )

        # Should not raise
        config.validate()

    def test_config_validation_dual_mode_requires_vault_type(self):
        """Test dual mode requires vault_storage_type."""
        config = Config(
            storage_mode="dual",
            storage_type="sqlite",
            db_path="data/core.db",
            vault_storage_type=None,  # Missing!
            vault_db_path="data/vault.db",
        )

        with pytest.raises(ValueError):
            config.validate()

    def test_config_validation_dual_sqlite_requires_vault_path(self):
        """Test dual mode with SQLite requires vault_db_path."""
        config = Config(
            storage_mode="dual",
            storage_type="sqlite",
            db_path="data/core.db",
            vault_storage_type="sqlite",
            vault_db_path=None,  # Missing!
        )

        with pytest.raises(ValueError):
            config.validate()

    def test_config_from_env_single_mode(self):
        """Test Config.from_env() with single mode defaults."""
        # from_env() defaults to single mode
        config = Config.from_env()
        assert config.storage_mode == "single"

    def test_config_from_env_dual_mode(self, monkeypatch):
        """Test Config.from_env() with dual mode env vars."""
        monkeypatch.setenv("RUNTIME_STORAGE_MODE", "dual")
        monkeypatch.setenv("RUNTIME_STORAGE_TYPE", "sqlite")
        monkeypatch.setenv("RUNTIME_DB_PATH", "/tmp/core.db")
        monkeypatch.setenv("RUNTIME_VAULT_STORAGE_TYPE", "sqlite")
        monkeypatch.setenv("RUNTIME_VAULT_DB_PATH", "/tmp/vault.db")

        config = Config.from_env()

        assert config.storage_mode == "dual"
        assert config.vault_storage_type == "sqlite"
        assert config.vault_db_path == "/tmp/vault.db"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
