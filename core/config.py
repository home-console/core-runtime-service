"""
Конфигурация Core Runtime.

Минимальные настройки.
"""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class Config:
    """Конфигурация Core Runtime."""
    # Тип адаптера: "sqlite" или "postgresql"
    storage_type: str = "sqlite"
    
    # Путь к файлу БД (для SQLite)
    db_path: str = "data/runtime.db"

    # PostgreSQL настройки
    pg_host: str = "localhost"
    pg_port: int = 5432
    pg_database: str = "homeconsole"
    pg_user: str = "postgres"
    pg_password: str = ""
    pg_dsn: Optional[str] = None  # Если указан, остальные pg_* игнорируются

    # Тайм-аут для shutdown (секунды)
    shutdown_timeout: int = 10
    
    # Тайм-аут для вызовов сервисов (секунды)
    # Защита от зависших вызовов плагинов
    service_call_timeout: float = 30.0

    def validate(self) -> None:
        """
        Валидировать конфигурацию.
        
        Raises:
            ValueError: если конфигурация невалидна
        """
        # Валидация storage_type
        if self.storage_type not in ("sqlite", "postgresql"):
            raise ValueError(
                f"storage_type must be 'sqlite' or 'postgresql', got: {self.storage_type!r}"
            )
        
        # Валидация SQLite параметров
        if self.storage_type == "sqlite":
            if not self.db_path:
                raise ValueError("db_path must be non-empty for SQLite storage")
            if not isinstance(self.db_path, str):
                raise ValueError(f"db_path must be string, got: {type(self.db_path).__name__}")
        
        # Валидация PostgreSQL параметров
        if self.storage_type == "postgresql":
            if not self.pg_dsn:
                # Если DSN не указан, проверяем отдельные параметры
                if not self.pg_database:
                    raise ValueError("pg_database must be non-empty for PostgreSQL storage")
                if not self.pg_user:
                    raise ValueError("pg_user must be non-empty for PostgreSQL storage")
                if not isinstance(self.pg_host, str):
                    raise ValueError(f"pg_host must be string, got: {type(self.pg_host).__name__}")
                if not isinstance(self.pg_port, int) or self.pg_port <= 0 or self.pg_port > 65535:
                    raise ValueError(
                        f"pg_port must be integer between 1 and 65535, got: {self.pg_port}"
                    )
        
        # Валидация shutdown_timeout
        if not isinstance(self.shutdown_timeout, int) or self.shutdown_timeout <= 0:
            raise ValueError(
                f"shutdown_timeout must be positive integer, got: {self.shutdown_timeout}"
            )

    @classmethod
    def from_env(cls) -> "Config":
        """
        Создать конфигурацию из переменных окружения.
        
        Raises:
            ValueError: если конфигурация невалидна
        """
        config = cls(
            storage_type=os.getenv("RUNTIME_STORAGE_TYPE", "sqlite"),
            db_path=os.getenv("RUNTIME_DB_PATH", "data/runtime.db"),
            pg_host=os.getenv("RUNTIME_PG_HOST", "localhost"),
            pg_port=int(os.getenv("RUNTIME_PG_PORT", "5432")),
            pg_database=os.getenv("RUNTIME_PG_DATABASE", "homeconsole"),
            pg_user=os.getenv("RUNTIME_PG_USER", "postgres"),
            pg_password=os.getenv("RUNTIME_PG_PASSWORD", ""),
            pg_dsn=os.getenv("RUNTIME_PG_DSN"),
            shutdown_timeout=int(os.getenv("RUNTIME_SHUTDOWN_TIMEOUT", "10")),
            service_call_timeout=float(os.getenv("RUNTIME_SERVICE_CALL_TIMEOUT", "30.0")),
        )
        config.validate()
        return config
