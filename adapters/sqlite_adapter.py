"""
SQLite адаптер для Storage API.

Простейшая реализация без ORM.
Одна таблица: namespace | key | value (JSON as TEXT).
"""

import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

from .storage_adapter import StorageAdapter


class SQLiteAdapter(StorageAdapter):
    """SQLite адаптер для key-value хранилища с namespace."""

    def __init__(self, db_path: str = "data.db"):
        """
        Инициализация SQLite адаптера.
        
        Args:
            db_path: путь к файлу базы данных (или ':memory:' для in-memory БД)
        """
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._ensure_db_exists()

    def _ensure_db_exists(self) -> None:
        """Создать таблицу, если её нет."""
        # Создать директорию только если это не :memory:
        if self.db_path != ':memory:':
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        
        # Для :memory: создаём connection сразу и сохраняем
        if self.db_path == ':memory:':
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn = self._conn
        else:
            conn = sqlite3.connect(self.db_path)
        
        conn.execute("""
            CREATE TABLE IF NOT EXISTS storage (
                namespace TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                PRIMARY KEY (namespace, key)
            )
        """)
        conn.commit()
        
        # Для обычной БД закрываем временное соединение
        if self.db_path != ':memory:':
            conn.close()

    def _get_connection(self) -> sqlite3.Connection:
        """Получить соединение с БД."""
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        return self._conn

    async def get(self, namespace: str, key: str) -> Optional[dict[str, Any]]:
        """Получить значение из storage."""
        conn = self._get_connection()
        cursor = conn.execute(
            "SELECT value FROM storage WHERE namespace = ? AND key = ?",
            (namespace, key)
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    async def set(self, namespace: str, key: str, value: dict[str, Any]) -> None:
        """Сохранить значение в storage."""
        conn = self._get_connection()
        json_value = json.dumps(value, ensure_ascii=False)
        conn.execute(
            "INSERT OR REPLACE INTO storage (namespace, key, value) VALUES (?, ?, ?)",
            (namespace, key, json_value)
        )
        conn.commit()

    async def delete(self, namespace: str, key: str) -> bool:
        """Удалить значение из storage."""
        conn = self._get_connection()
        cursor = conn.execute(
            "DELETE FROM storage WHERE namespace = ? AND key = ?",
            (namespace, key)
        )
        conn.commit()
        return cursor.rowcount > 0

    async def list_keys(self, namespace: str) -> list[str]:
        """Получить список ключей в namespace."""
        conn = self._get_connection()
        cursor = conn.execute(
            "SELECT key FROM storage WHERE namespace = ?",
            (namespace,)
        )
        return [row[0] for row in cursor.fetchall()]

    async def clear_namespace(self, namespace: str) -> None:
        """Очистить все записи в namespace."""
        conn = self._get_connection()
        conn.execute("DELETE FROM storage WHERE namespace = ?", (namespace,))
        conn.commit()

    async def close(self) -> None:
        """Закрыть соединение с БД."""
        if self._conn:
            self._conn.close()
            self._conn = None
