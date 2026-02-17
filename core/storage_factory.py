"""
Фабрика для создания storage адаптеров и managers.

Позволяет создавать разные адаптеры (SQLite, PostgreSQL) на основе конфигурации.
Поддерживает Storage v3 dual-mode с отдельными хранилищами для Core и Vault.
"""

from typing import Any

from core.config import Config
from adapters.storage_adapter import StorageAdapter
from core.storage_manager import StorageManager
from core.storage_errors import StorageConfigurationError


async def create_storage_adapter(config: Config) -> StorageAdapter:
    """
    Создать storage адаптер на основе конфигурации (для одного хранилища).

    Args:
        config: конфигурация Core Runtime (должна быть валидирована)

    Returns:
        экземпляр StorageAdapter

    Raises:
        ValueError: если указан неизвестный тип адаптера или конфигурация невалидна
        ImportError: если для PostgreSQL не установлен asyncpg
    """
    # Валидируем конфигурацию перед созданием адаптера
    config.validate()
    
    if config.storage_type == "sqlite":
        from adapters.sqlite_adapter import SQLiteAdapter
        adapter = SQLiteAdapter(config.db_path)
        await adapter.initialize_schema()
        return adapter

    elif config.storage_type == "postgresql":
        from adapters.postgresql_adapter import PostgreSQLAdapter
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

    else:
        raise ValueError(
            f"Неизвестный тип storage: {config.storage_type}. "
            f"Доступные типы: sqlite, postgresql"
        )


async def _create_vault_storage_adapter(config: Config) -> StorageAdapter:
    """
    Создать vault storage адаптер для dual-mode.
    
    Args:
        config: конфигурация Core Runtime (должна быть валидирована в dual-mode)
    
    Returns:
        экземпляр StorageAdapter для vault хранилища
    
    Raises:
        StorageConfigurationError: если конфигурация невалидна для dual mode
    """
    if config.storage_mode != "dual":
        raise StorageConfigurationError(
            f"_create_vault_storage_adapter requires storage_mode='dual', got {config.storage_mode!r}"
        )
    
    if not config.vault_storage_type:
        raise StorageConfigurationError(
            "vault_storage_type must be set in dual mode"
        )
    
    if config.vault_storage_type == "sqlite":
        if not config.vault_db_path:
            raise StorageConfigurationError(
                "vault_db_path must be set for SQLite vault storage"
            )
        from adapters.sqlite_adapter import SQLiteAdapter
        adapter = SQLiteAdapter(config.vault_db_path)
        await adapter.initialize_schema()
        return adapter
    
    elif config.vault_storage_type == "postgresql":
        if not config.vault_pg_dsn:
            raise StorageConfigurationError(
                "vault_pg_dsn must be set for PostgreSQL vault storage"
            )
        from adapters.postgresql_adapter import PostgreSQLAdapter
        adapter = PostgreSQLAdapter(dsn=config.vault_pg_dsn)
        await adapter.initialize_schema()
        return adapter
    
    else:
        raise StorageConfigurationError(
            f"Invalid vault_storage_type: {config.vault_storage_type}; "
            f"must be 'sqlite' or 'postgresql'"
        )


async def create_storage_manager(config: Config) -> StorageManager:
    """
    Создать StorageManager с поддержкой single и dual mode.
    
    Single mode (default, backward compatible):
    - Один адаптер для всех операций
    - RUNTIME_STORAGE_MODE=single (default)
    
    Dual mode (Storage v3 with vault isolation):
    - Два адаптера: core_storage и vault_storage
    - RUNTIME_STORAGE_MODE=dual
    - Требует конфигурации vault хранилища
    - Обеспечивает физическую изоляцию секретов
    
    Args:
        config: конфигурация Core Runtime (должна быть валидирована)
    
    Returns:
        экземпляр StorageManager
    
    Raises:
        StorageConfigurationError: если конфигурация dual mode невалидна
        ValueError: если storage_type неизвестен
    """
    # Валидируем конфигурацию перед созданием
    config.validate()
    
    # Создаем core storage
    core_storage = await create_storage_adapter(config)
    
    # Для dual mode создаем отдельное vault хранилище
    vault_storage = None
    if config.storage_mode == "dual":
        vault_storage = await _create_vault_storage_adapter(config)
    
    # Создаем manager
    manager = StorageManager(
        core_storage=core_storage,
        vault_storage=vault_storage,
        mode=config.storage_mode,
    )
    
    return manager

