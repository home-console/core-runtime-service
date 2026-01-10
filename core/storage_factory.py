"""
Фабрика для создания storage адаптеров.

Позволяет создавать разные адаптеры (SQLite, PostgreSQL) на основе конфигурации.
"""

from typing import Any

from core.config import Config
from adapters.storage_adapter import StorageAdapter


async def create_storage_adapter(config: Config) -> StorageAdapter:
    """
    Создать storage адаптер на основе конфигурации.

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
