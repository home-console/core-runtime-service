"""
Конфигурация Core Runtime.

Минимальные настройки.
"""

import os
from dataclasses import dataclass


@dataclass
class Config:
    """Конфигурация Core Runtime."""
    # Путь к файлу БД
    db_path: str = "data/runtime.db"

    # Таймаут для shutdown (секунды)
    shutdown_timeout: int = 10

    @classmethod
    def from_env(cls) -> "Config":
        """
        Создать конфигурацию из переменных окружения.
        """
        return cls(
            db_path=os.getenv("RUNTIME_DB_PATH", "data/runtime.db"),
            shutdown_timeout=int(os.getenv("RUNTIME_SHUTDOWN_TIMEOUT", "10")),
        )
