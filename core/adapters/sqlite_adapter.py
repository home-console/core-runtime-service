"""
SQLite адаптер для Storage API.

Простейшая реализация без ORM.
Одна таблица: namespace | key | value (JSON as TEXT).
"""

import asyncio
import json
import logging
import os
import sqlite3
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Optional

from core.adapters.storage_errors import StorageCorruptionError
from core.exception_groups import BEST_EFFORT_BACKGROUND_ERRORS

from .storage_adapter import StorageAdapter

logger = logging.getLogger(__name__)


class SQLiteAdapter(StorageAdapter):
    """SQLite адаптер для key-value хранилища с namespace.

    Все блокирующие операции выполняются в threadpool через `asyncio.to_thread`.
    Инициализация схемы не выполняется автоматически — отдельный метод
    `initialize_schema()` должен быть вызван явно.

    CRITICAL: Использует thread-local storage для SQLite connections, чтобы избежать
    InterfaceError при параллельных запросах из разных потоков.
    """

    def __init__(self, db_path: str = "data.db"):
        """
        Инициализация адаптера (без создания схемы).

        Args:
            db_path: путь к файлу базы данных (или ':memory:' для in-memory БД)
        """
        self.db_path = db_path
        self._local = (
            threading.local()
        )  # Thread-local storage для connections и transactions

    def _get_connection(self, *, readonly: bool = False) -> sqlite3.Connection:
        """Создать или вернуть thread-local соединение.

        CRITICAL: Каждый поток получает свое собственное соединение, чтобы избежать
        InterfaceError: bad parameter or other API misuse при параллельных запросах.

        CRASH SAFETY (Part A):
        - PRAGMA journal_mode=WAL: Write-Ahead Logging для аварийной безопасности
        - PRAGMA synchronous=FULL: fsync после каждого транзакции (дорого, но безопасно)
        - PRAGMA cache_size=-64000: 64MB кэш для производительности
        - PRAGMA foreign_keys=ON: включить проверку foreign keys
        - PRAGMA wal_autocheckpoint=1000: checkpoints каждые 1000 страниц
        """
        attr = "conn_ro" if readonly else "conn_rw"
        conn = getattr(self._local, attr, None)
        if conn is None:
            # Создаем новое соединение для текущего потока
            conn = sqlite3.connect(
                self.db_path,
                check_same_thread=True,  # Теперь каждый поток имеет свое соединение
                timeout=30.0,  # Таймаут для database locked ситуаций
            )
            setattr(self._local, attr, conn)

            # ┌─────────────────────────────────────────────────────────┐
            # │ CRASH SAFETY PRAGMAS                                    │
            # └─────────────────────────────────────────────────────────┘

            # Write-Ahead Logging (WAL mode)
            # Гарантирует, что читатели не заблокируют писателей
            conn.execute("PRAGMA journal_mode=WAL")

            # FULL synchronous mode
            # Требует fsync после каждого COMMIT
            # Это гарантирует, что данные на диске даже при крахе ОС
            conn.execute("PRAGMA synchronous=FULL")

            # Большой кэш для производительности (64MB)
            # Отрицательное число = кэш в килобайтах
            conn.execute("PRAGMA cache_size=-64000")

            # Включить проверку foreign keys
            conn.execute("PRAGMA foreign_keys=ON")

            # WAL checkpoints каждые 1000 страниц (вместо default 1000000)
            # Меньше означает более частые checkpoints, но более консервативно
            conn.execute("PRAGMA wal_autocheckpoint=1000")

            # Проверить, что synchronous действительно FULL
            cursor = conn.execute("PRAGMA synchronous")
            sync_mode = cursor.fetchone()[0]
            # synchronous: 0=OFF, 1=NORMAL, 2=FULL, 3=EXTRA
            if sync_mode != 2:
                # `os` is imported at module level; avoid re-importing here which
                # would make `os` a local variable and cause UnboundLocalError
                logger.warning(
                    "[SQLiteAdapter] PRAGMA synchronous=%d, expected 2 (FULL). "
                    "This may result in data loss on crash.",
                    sync_mode
                )

            # Проверить Docker overlayfs (частая проблема в контейнерах)
            if readonly:
                # Ensure this connection is used for reads only.
                try:
                    conn.execute("PRAGMA query_only=ON")
                except Exception:
                    logger.debug("[SQLiteAdapter] Failed to enable PRAGMA query_only=ON", exc_info=True)

            if self.db_path != ":memory:" and os.path.exists("/proc/mounts"):
                try:
                    with open("/proc/mounts", "r") as f:
                        mounts = f.read()
                        if (
                            "overlay" in mounts
                            and self.db_path in mounts
                            or "/app" in self.db_path
                        ):
                            logger.warning(
                                "[SQLiteAdapter] Database may be on Docker overlayfs. "
                                "This can cause durability issues. Consider using named volumes."
                            )
                except OSError:
                    logger.warning(
                        "sqlite_adapter._get_connection: /proc/mounts check failed; overlayfs durability checks skipped",
                        exc_info=True,
                    )

        return conn

    def _get_in_transaction(self) -> bool:
        """Получить thread-local флаг транзакции."""
        return getattr(self._local, "in_transaction", False)

    def _set_in_transaction(self, value: bool) -> None:
        """Установить thread-local флаг транзакции."""
        self._local.in_transaction = value

    def _create_schema_sync(self) -> None:
        """Синхронная функция создания таблицы схемы."""
        conn = self._get_connection(readonly=False)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS storage (
                namespace TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                PRIMARY KEY (namespace, key)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS storage_metadata (
                key TEXT NOT NULL PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        # Schema version for forward-compatible migrations.
        conn.execute("""
            INSERT OR IGNORE INTO storage_metadata (key, value)
            VALUES ('schema_version', '1')
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
        """Получить значение из storage (выполняется в threadpool).

        CORRUPTION DETECTION (Part A):
        - Если JSON не парсится → StorageCorruptionError
        - Если значение не dict → StorageCorruptionError
        - Иначе возвращает dict или None если не найдено
        """

        def _get_sync(ns: str, k: str):
            conn = self._get_connection(readonly=True)
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
                raise StorageCorruptionError(
                    f"Invalid value type in storage: expected str/bytes/bytearray, "
                    f"got {type(value).__name__} for {ns}.{k}"
                )
            try:
                parsed = json.loads(value)
                if not isinstance(parsed, dict):
                    raise StorageCorruptionError(
                        f"Invalid JSON structure in storage for {ns}.{k}: "
                        f"expected dict, got {type(parsed).__name__}"
                    )
                return parsed
            except json.JSONDecodeError as e:
                raise StorageCorruptionError(f"JSON parsing error for {ns}.{k}: {e}")

        return await asyncio.to_thread(_get_sync, namespace, key)

    async def set(self, namespace: str, key: str, value: dict[str, Any]) -> None:
        """Сохранить значение в storage (выполняется в threadpool)."""

        def _set_sync(ns: str, k: str, v: dict[str, Any], in_transaction: bool):
            conn = self._get_connection(readonly=False)
            json_value = json.dumps(v, ensure_ascii=False)
            conn.execute(
                "INSERT OR REPLACE INTO storage (namespace, key, value) VALUES (?, ?, ?)",
                (ns, k, json_value),
            )
            # Не делаем commit если мы в транзакции
            if not in_transaction:
                # CRITICAL: ВСЕГДА делаем commit и выбрасываем исключение при ошибке
                # Подавление ошибок commit() приводит к сохранению битых данных
                # и потере токенов OAuth (токены записываются, но не коммитятся)
                conn.commit()

        await asyncio.to_thread(
            _set_sync, namespace, key, value, self._get_in_transaction()
        )

    async def delete(self, namespace: str, key: str) -> bool:
        """Удалить значение из storage (выполняется в threadpool)."""

        def _delete_sync(ns: str, k: str, in_transaction: bool):
            conn = self._get_connection(readonly=False)
            cursor = conn.execute(
                "DELETE FROM storage WHERE namespace = ? AND key = ?",
                (ns, k),
            )
            # Не делаем commit если мы в транзакции
            if not in_transaction:
                # CRITICAL: ВСЕГДА делаем commit и выбрасываем исключение при ошибке
                conn.commit()
            return cursor.rowcount > 0

        return await asyncio.to_thread(
            _delete_sync, namespace, key, self._get_in_transaction()
        )

    def _set_with_conn(
        self, conn: sqlite3.Connection, namespace: str, key: str, value: dict[str, Any]
    ) -> None:
        """Синхронная запись с явным conn (для run_atomic — одна транзакция в одном потоке)."""
        json_value = json.dumps(value, ensure_ascii=False)
        conn.execute(
            "INSERT OR REPLACE INTO storage (namespace, key, value) VALUES (?, ?, ?)",
            (namespace, key, json_value),
        )

    def _get_with_conn(
        self, conn: sqlite3.Connection, namespace: str, key: str
    ) -> Optional[dict[str, Any]]:
        """Синхронное чтение с явным conn."""
        cursor = conn.execute(
            "SELECT value FROM storage WHERE namespace = ? AND key = ?",
            (namespace, key),
        )
        row = cursor.fetchone()
        if row is None or row[0] is None:
            return None
        parsed = json.loads(row[0])
        return parsed if isinstance(parsed, dict) else None

    def _list_keys_with_conn(
        self, conn: sqlite3.Connection, namespace: str
    ) -> list[str]:
        """Синхронный list_keys с явным conn."""
        cursor = conn.execute(
            "SELECT key FROM storage WHERE namespace = ?", (namespace,)
        )
        return [row[0] for row in cursor.fetchall()]

    def _delete_with_conn(
        self, conn: sqlite3.Connection, namespace: str, key: str
    ) -> bool:
        """Синхронное удаление с явным conn. Возвращает True если строка удалена."""
        cursor = conn.execute(
            "DELETE FROM storage WHERE namespace = ? AND key = ?",
            (namespace, key),
        )
        return cursor.rowcount > 0

    async def run_atomic(
        self, sync_fn: Callable[[sqlite3.Connection, "SQLiteAdapter"], Any]
    ) -> Any:
        """
        Выполнить sync_fn(conn, self) в одном потоке в одной транзакции (BEGIN ... COMMIT).
        Устраняет "database is locked": все операции в одной conn.
        """

        def _run():
            conn = self._get_connection(readonly=False)
            conn.execute("BEGIN")
            try:
                result = sync_fn(conn, self)
                conn.commit()
                return result
            except BEST_EFFORT_BACKGROUND_ERRORS:
                conn.rollback()
                raise

        return await asyncio.to_thread(_run)

    async def list_keys(self, namespace: str) -> list[str]:
        """Получить список ключей в namespace (выполняется в threadpool)."""

        def _list_keys_sync(ns: str):
            conn = self._get_connection(readonly=True)
            cursor = conn.execute("SELECT key FROM storage WHERE namespace = ?", (ns,))
            return [row[0] for row in cursor.fetchall()]

        return await asyncio.to_thread(_list_keys_sync, namespace)

    async def list_namespaces(self) -> list[str]:
        """Получить список всех namespace (выполняется в threadpool)."""

        def _list_namespaces_sync():
            conn = self._get_connection(readonly=True)
            cursor = conn.execute("SELECT DISTINCT namespace FROM storage")
            return sorted(row[0] for row in cursor.fetchall())

        return await asyncio.to_thread(_list_namespaces_sync)

    async def clear_namespace(self, namespace: str) -> None:
        """Очистить все записи в namespace (выполняется в threadpool)."""

        def _clear_sync(ns: str, in_transaction: bool):
            conn = self._get_connection(readonly=False)
            conn.execute("DELETE FROM storage WHERE namespace = ?", (ns,))
            # Не делаем commit если мы в транзакции
            if not in_transaction:
                # CRITICAL: ВСЕГДА делаем commit и выбрасываем исключение при ошибке
                conn.commit()

        await asyncio.to_thread(_clear_sync, namespace, self._get_in_transaction())

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
            conn = self._get_connection(readonly=False)
            conn.execute("BEGIN")

        def _commit_sync():
            conn = self._get_connection(readonly=False)
            conn.commit()

        def _rollback_sync():
            conn = self._get_connection(readonly=False)
            conn.rollback()

        # Начинаем транзакцию
        self._set_in_transaction(True)
        await asyncio.to_thread(_begin_sync)

        try:
            yield
            # Коммитим транзакцию
            await asyncio.to_thread(_commit_sync)
        except BEST_EFFORT_BACKGROUND_ERRORS:
            # Откатываем транзакцию при ошибке
            await asyncio.to_thread(_rollback_sync)
            raise
        finally:
            self._set_in_transaction(False)

    async def batch_set(self, namespace: str, items: dict[str, dict[str, Any]]) -> None:
        """Массовая запись значений в namespace (выполняется в threadpool)."""

        def _batch_set_sync(
            ns: str, items_dict: dict[str, dict[str, Any]], in_transaction: bool
        ):
            conn = self._get_connection(readonly=False)
            for key, value in items_dict.items():
                json_value = json.dumps(value, ensure_ascii=False)
                conn.execute(
                    "INSERT OR REPLACE INTO storage (namespace, key, value) VALUES (?, ?, ?)",
                    (ns, key, json_value),
                )
            # Не делаем commit если мы в транзакции
            if not in_transaction:
                # CRITICAL: ВСЕГДА делаем commit и выбрасываем исключение при ошибке
                conn.commit()

        await asyncio.to_thread(
            _batch_set_sync, namespace, items, self._get_in_transaction()
        )

    async def iter_namespace(
        self, namespace: str, batch_size: int = 100
    ) -> "AsyncIterator[tuple[str, dict[str, Any]]]":
        """
        Итерировать по всем ключам в namespace батчами (для efficient streaming больших namespace).

        Args:
            namespace: пространство имён
            batch_size: размер батча для fetch (default 100)

        Yields:
            (key, value) кортежи
        """

        def _iter_namespace_generator(ns: str, batch: int):
            """Синхронный генератор для итерации.

            Гарантирует, что value всегда dict[str, Any], как требует интерфейс StorageAdapter.
            Некорректные JSON‑значения или не‑dict пропускаются.
            """
            conn = self._get_connection(readonly=True)
            offset = 0
            while True:
                cursor = conn.execute(
                    "SELECT key, value FROM storage WHERE namespace = ? LIMIT ? OFFSET ?",
                    (ns, batch, offset),
                )
                rows = cursor.fetchall()
                if not rows:
                    break
                for key, json_value in rows:
                    try:
                        value = json.loads(json_value)
                    except (json.JSONDecodeError, ValueError, TypeError):
                        # Пропускаем записи с битым JSON
                        continue
                    # Гарантируем dict[str, Any] как контракт интерфейса
                    if not isinstance(value, dict):
                        continue
                    yield key, value
                offset += batch

        # Запустить генератор в threadpool
        async def _async_iter():
            for key, value in await asyncio.to_thread(
                _iter_namespace_generator, namespace, batch_size
            ):
                yield key, value

        # Вернуть async iterator
        async for item in _async_iter():
            yield item

    async def close(self) -> None:
        """Закрыть thread-local соединение с БД (выполняется в threadpool)."""

        def _close_sync():
            # Закрываем только соединения текущего потока
            if hasattr(self._local, "conn_rw") and self._local.conn_rw is not None:
                try:
                    self._local.conn_rw.close()
                finally:
                    self._local.conn_rw = None
            if hasattr(self._local, "conn_ro") and self._local.conn_ro is not None:
                try:
                    self._local.conn_ro.close()
                finally:
                    self._local.conn_ro = None

        await asyncio.to_thread(_close_sync)
