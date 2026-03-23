"""
Storage adapter factory and stack assembly for application/runtime composition.

This module lives in modules layer because it wires storage policies
(startup checks, dual-mode vault wrapping, secure wrapper usage).
"""

from core.adapters.storage_adapter import StorageAdapter
from core.config import Config
from core.state_engine import StateEngine
from modules.storage.errors import StorageConfigurationError
from modules.storage.manager import StorageManager
from modules.storage.port import CoreStoragePort, StorageStack, VaultStoragePort
from modules.storage.secure import SecureStorageWrapper
from modules.storage.startup import StorageStartupChecker


async def create_storage_adapter(config: Config) -> StorageAdapter:
    """Create single storage adapter from config."""
    config.validate()

    if config.storage_type == "sqlite":
        from core.adapters.sqlite_adapter import SQLiteAdapter

        adapter = SQLiteAdapter(config.db_path)
        await adapter.initialize_schema()
        return adapter

    if config.storage_type == "postgresql":
        from core.adapters.postgresql_adapter import PostgreSQLAdapter

        adapter = PostgreSQLAdapter(
            host=config.pg_host,
            port=config.pg_port,
            database=config.pg_database,
            user=config.pg_user,
            password=config.pg_password,
            dsn=config.pg_dsn,
        )
        await adapter.initialize_schema()
        return adapter

    raise ValueError(
        f"Неизвестный тип storage: {config.storage_type}. "
        f"Доступные типы: sqlite, postgresql"
    )


async def _create_vault_storage_adapter(config: Config) -> StorageAdapter:
    """Create vault adapter for dual-mode storage."""
    if config.storage_mode != "dual":
        raise StorageConfigurationError(
            f"_create_vault_storage_adapter requires storage_mode='dual', got {config.storage_mode!r}"
        )
    if not config.vault_storage_type:
        raise StorageConfigurationError("vault_storage_type must be set in dual mode")

    if config.vault_storage_type == "sqlite":
        if not config.vault_db_path:
            raise StorageConfigurationError(
                "vault_db_path must be set for SQLite vault storage"
            )
        from core.adapters.sqlite_adapter import SQLiteAdapter

        adapter = SQLiteAdapter(config.vault_db_path)
        await adapter.initialize_schema()
        return adapter

    if config.vault_storage_type == "postgresql":
        if not config.vault_pg_dsn:
            raise StorageConfigurationError(
                "vault_pg_dsn must be set for PostgreSQL vault storage"
            )
        from core.adapters.postgresql_adapter import PostgreSQLAdapter

        adapter = PostgreSQLAdapter(dsn=config.vault_pg_dsn)
        await adapter.initialize_schema()
        return adapter

    raise StorageConfigurationError(
        f"Invalid vault_storage_type: {config.vault_storage_type}; "
        f"must be 'sqlite' or 'postgresql'"
    )


async def create_storage_manager(config: Config) -> StorageManager:
    """Create storage manager for single/dual mode."""
    config.validate()
    core_storage = await create_storage_adapter(config)
    vault_storage = None
    if config.storage_mode == "dual":
        vault_storage = await _create_vault_storage_adapter(config)
    return StorageManager(
        core_storage=core_storage,
        vault_storage=vault_storage,
        mode=config.storage_mode,
    )


async def build_storage_stack(config: Config, state_engine: StateEngine) -> StorageStack:
    """Build full storage stack for runtime startup."""
    checker = StorageStartupChecker(config)
    await checker.check_all()

    core_adapter = await create_storage_adapter(config)
    vault_adapter = None
    secure_storage = None
    if config.storage_mode == "dual":
        vault_adapter = await _create_vault_storage_adapter(config)
        secure_storage = SecureStorageWrapper(vault_adapter)
        await secure_storage.initialize()

    vault_backend = secure_storage if secure_storage else vault_adapter
    manager = StorageManager(
        core_storage=core_adapter,
        vault_storage=vault_backend,
        mode=config.storage_mode,
    )
    core_port = CoreStoragePort(core_adapter, state_engine)
    vault_port = VaultStoragePort(secure_storage) if secure_storage else None

    return StorageStack(
        manager=manager,
        core_port=core_port,
        vault_port=vault_port,
    )
