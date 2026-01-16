"""
SQLite адаптер для Storage API.

Простейшая реализация без ORM.
Одна таблица: namespace | key | value (JSON as TEXT).
"""

import json
import sqlite3
from pathlib import Path
from typing import Any, Optional
import asyncio
from contextlib import asynccontextmanager

from .storage_adapter import StorageAdapter


class SQLiteAdapter(StorageAdapter):
    """SQLite адаптер для key-value хранилища с namespace.

    Все блокирующие операции выполняются в threadpool через `asyncio.to_thread`.
    Инициализация схемы не выполняется автоматически — отдельный метод
    `initialize_schema()` должен быть вызван явно.
    """

    def __init__(self, db_path: str = "data.db"):
        """
        Инициализация адаптера (без создания схемы).

        Args:
            db_path: путь к файлу базы данных (или ':memory:' для in-memory БД)
        """
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._in_transaction: bool = False

    def _get_connection(self) -> sqlite3.Connection:
        """Создать или вернуть существующее соединение.

        Соединение создается с `check_same_thread=False`, чтобы его можно было
        безопасно использовать из разных потоков через threadpool.
        """
        if self._conn is None:
            # Для файловой БД создаём директорию при явной инициализации схемы,
            # здесь только создаём соединение.
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        return self._conn

    def _create_schema_sync(self) -> None:
        """Синхронная функция создания таблицы схемы."""
        conn = self._get_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS storage (
                namespace TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                PRIMARY KEY (namespace, key)
            )
        """)
        conn.commit()

    async def initialize_schema(self) -> None:
        """Явная инициализация схемы хранилища.

        Для файловой БД создаёт директорию и таблицу. Для ':memory:' просто
        создаёт таблицу в in-memory БД.
        """
        # Создать директорию только если это не :memory:
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        await asyncio.to_thread(self._create_schema_sync)

    async def get(self, namespace: str, key: str) -> Optional[dict[str, Any]]:
        """Получить значение из storage (выполняется в threadpool)."""

        def _get_sync(ns: str, k: str):
            conn = self._get_connection()
            cursor = conn.execute(
                "SELECT value FROM storage WHERE namespace = ? AND key = ?",
                (ns, k),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            # Проверяем, что значение не None
            value = row[0]
            if value is None:
                return None
            # Проверяем, что это строка перед десериализацией
            if not isinstance(value, (str, bytes, bytearray)):
                return None
            try:
                return json.loads(value)
            except (json.JSONDecodeError, ValueError, TypeError) as e:
                # Логируем ошибку парсинга, но не падаем
                # Возвращаем None, чтобы система могла продолжить работу
                import sys
                print(
                    f"[SQLiteAdapter] Ошибка парсинга JSON для {ns}.{k}: {e}",
                    file=sys.stderr
                )
                return None

        return await asyncio.to_thread(_get_sync, namespace, key)

    async def set(self, namespace: str, key: str, value: dict[str, Any]) -> None:
        """Сохранить значение в storage (выполняется в threadpool)."""

        def _set_sync(ns: str, k: str, v: dict[str, Any], in_transaction: bool):
            conn = self._get_connection()
            json_value = json.dumps(v, ensure_ascii=False)
            conn.execute(
                "INSERT OR REPLACE INTO storage (namespace, key, value) VALUES (?, ?, ?)",
                (ns, k, json_value),
            )
            # Не делаем commit если мы в транзакции
            if not in_transaction:
                try:
                    conn.commit()
                except sqlite3.OperationalError as e:
                    # Игнорируем ошибки типа "cannot commit - no transaction is active"
                    # Это может произойти, если connection уже закрыт или транзакция не активна
                    if "transaction" not in str(e).lower():
                        raise

        await asyncio.to_thread(_set_sync, namespace, key, value, self._in_transaction)

    async def delete(self, namespace: str, key: str) -> bool:
        """Удалить значение из storage (выполняется в threadpool)."""

        def _delete_sync(ns: str, k: str, in_transaction: bool):
            conn = self._get_connection()
            cursor = conn.execute(
                "DELETE FROM storage WHERE namespace = ? AND key = ?",
                (ns, k),
            )
            # Не делаем commit если мы в транзакции
            if not in_transaction:
                try:
                    conn.commit()
                except sqlite3.OperationalError as e:
                    # Игнорируем ошибки типа "cannot commit - no transaction is active"
                    if "transaction" not in str(e).lower():
                        raise
            return cursor.rowcount > 0

        return await asyncio.to_thread(_delete_sync, namespace, key, self._in_transaction)

    async def list_keys(self, namespace: str) -> list[str]:
        """Получить список ключей в namespace (выполняется в threadpool)."""

        def _list_keys_sync(ns: str):
            conn = self._get_connection()
            cursor = conn.execute("SELECT key FROM storage WHERE namespace = ?", (ns,))
            return [row[0] for row in cursor.fetchall()]

        return await asyncio.to_thread(_list_keys_sync, namespace)

    async def clear_namespace(self, namespace: str) -> None:
        """Очистить все записи в namespace (выполняется в threadpool)."""

        def _clear_sync(ns: str, in_transaction: bool):
            conn = self._get_connection()
            conn.execute("DELETE FROM storage WHERE namespace = ?", (ns,))
            # Не делаем commit если мы в транзакции
            if not in_transaction:
                try:
                    conn.commit()
                except sqlite3.OperationalError as e:
                    # Игнорируем ошибки типа "cannot commit - no transaction is active"
                    if "transaction" not in str(e).lower():
                        raise

        await asyncio.to_thread(_clear_sync, namespace, self._in_transaction)
    
    @asynccontextmanager
    async def transaction(self):
        """
        Контекстный менеджер для транзакций SQLite.
        
        Использование:
            async with adapter.transaction():
                await adapter.set("ns", "key1", {"value": 1})
                await adapter.set("ns", "key2", {"value": 2})
                # Все операции выполняются в одной транзакции
        """
        def _begin_sync():
            conn = self._get_connection()
            conn.execute("BEGIN")
        
        def _commit_sync():
            conn = self._get_connection()
            conn.commit()
        
        def _rollback_sync():
            conn = self._get_connection()
            conn.rollback()
        
        # Начинаем транзакцию
        self._in_transaction = True
        await asyncio.to_thread(_begin_sync)
        
        try:
            yield
            # Коммитим транзакцию
            await asyncio.to_thread(_commit_sync)
        except Exception:
            # Откатываем транзакцию при ошибке
            await asyncio.to_thread(_rollback_sync)
            raise
        finally:
            self._in_transaction = False
    
    async def batch_set(self, namespace: str, items: dict[str, dict[str, Any]]) -> None:
        """Массовая запись значений в namespace (выполняется в threadpool)."""
        
        def _batch_set_sync(ns: str, items_dict: dict[str, dict[str, Any]], in_transaction: bool):
            conn = self._get_connection()
            for key, value in items_dict.items():
                json_value = json.dumps(value, ensure_ascii=False)
                conn.execute(
                    "INSERT OR REPLACE INTO storage (namespace, key, value) VALUES (?, ?, ?)",
                    (ns, key, json_value),
                )
            # Не делаем commit если мы в транзакции
            if not in_transaction:
                try:
                    conn.commit()
                except sqlite3.OperationalError as e:
                    # Игнорируем ошибки типа "cannot commit - no transaction is active"
                    if "transaction" not in str(e).lower():
                        raise
        
        await asyncio.to_thread(_batch_set_sync, namespace, items, self._in_transaction)

    async def close(self) -> None:
        """Закрыть соединение с БД (выполняется в threadpool)."""
        def _close_sync():
            if self._conn:
                try:
                    self._conn.close()
                finally:
                    self._conn = None

        await asyncio.to_thread(_close_sync)
