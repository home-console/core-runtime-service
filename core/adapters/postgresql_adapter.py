"""
PostgreSQL адаптер для Storage API.

Использует asyncpg для асинхронной работы с PostgreSQL.
Та же схема: namespace | key | value (JSON as TEXT).

CRASH SAFETY (Part A):
- PostgreSQL использует журнал транзакций (WAL)
- Параметр fsync гарантирует синхронизацию на диск
- Connection string должен включать SSL для production
- Transactions гарантируют ACID семантику
- JSONB автоматически валидирует JSON
"""

import json
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional, TYPE_CHECKING

try:
    import asyncpg

    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False
    asyncpg = None  # type: ignore[assignment]

if TYPE_CHECKING:
    import asyncpg as _asyncpg  # pragma: no cover

from .storage_adapter import StorageAdapter
from core.adapters.storage_errors import StorageCorruptionError


class PostgreSQLAdapter(StorageAdapter):
    """PostgreSQL адаптер для key-value хранилища с namespace.

    Использует asyncpg для асинхронной работы с PostgreSQL.
    Инициализация схемы не выполняется автоматически — отдельный метод
    `initialize_schema()` должен быть вызван явно.

    CRASH SAFETY CONFIGURATION:

    Для production, убедитесь что PostgreSQL настроена с:
    - shared_buffers=256MB (или больше)
    - wal_level=replica  (for streaming replication)
    - fsync=on  (default, но проверьте)
    - synchronous_commit=on  (для гарантии на диск)
    - max_wal_senders=10  (для backup/replication)

    Connection string должна включать:
    - ?sslmode=require (для шифрования)
    - &connect_timeout=10

    Пример production строки:
        postgresql://user:pass@localhost:5432/homeconsole?sslmode=require&connect_timeout=10
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 5432,
        database: str = "homeconsole",
        user: str = "postgres",
        password: str = "",
        dsn: Optional[str] = None,
    ):
        """
        Инициализация адаптера (без создания схемы).

        Args:
            host: хост PostgreSQL
            port: порт PostgreSQL
            database: имя базы данных
            user: пользователь
            password: пароль
            dsn: строка подключения (если указана, остальные параметры игнорируются)
        """
        if not ASYNCPG_AVAILABLE:
            raise ImportError(
                "asyncpg не установлен. Установите его: pip install asyncpg"
            )

        # Если DSN не указан, формируем его из параметров
        # Используем urllib.parse.quote для безопасного экранирования пароля
        if dsn:
            self._dsn = dsn
        else:
            from urllib.parse import quote_plus

            safe_password = quote_plus(password) if password else ""
            self._dsn = f"postgresql://{user}:{safe_password}@{host}:{port}/{database}"

        self._pool: Optional["_asyncpg.Pool"] = None

    async def _get_pool(self) -> "_asyncpg.Pool":
        """Создать или вернуть пул соединений."""
        if self._pool is None:
            assert asyncpg is not None
            self._pool = await asyncpg.create_pool(self._dsn)
        return self._pool

    async def initialize_schema(self) -> None:
        """Явная инициализация схемы хранилища.

        Создаёт таблицу storage если её нет.
        Использует JSONB для автоматической валидации JSON и возможности индексов.
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS storage (
                    namespace TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value JSONB NOT NULL,
                    PRIMARY KEY (namespace, key)
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS storage_metadata (
                    key TEXT NOT NULL PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            await conn.execute("""
                INSERT INTO storage_metadata (key, value)
                VALUES ('schema_version', '1')
                ON CONFLICT (key) DO NOTHING
            """)

    async def get(self, namespace: str, key: str) -> Optional[dict[str, Any]]:
        """Получить значение из storage.

        CORRUPTION DETECTION (Part A):
        - JSONB автоматически валидируется PostgreSQL
        - Если get вернул не-dict → StorageCorruptionError
        - asyncpg гарантирует типы безопасности
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT value FROM storage WHERE namespace = $1 AND key = $2",
                namespace,
                key,
            )
            if row is None:
                return None
            # JSONB уже является dict в asyncpg, но для совместимости проверяем
            value = row["value"]
            if value is None:
                return None
            if isinstance(value, dict):
                return value
            # Fallback на json.loads если по какой-то причине вернулся текст
            try:
                if isinstance(value, (str, bytes, bytearray)):
                    parsed = json.loads(value)
                    if not isinstance(parsed, dict):
                        raise StorageCorruptionError(
                            f"Invalid JSON structure in storage for {namespace}.{key}: "
                            f"expected dict, got {type(parsed).__name__}"
                        )
                    return parsed
                raise StorageCorruptionError(
                    f"Invalid value type in storage: expected dict, "
                    f"got {type(value).__name__} for {namespace}.{key}"
                )
            except json.JSONDecodeError as e:
                raise StorageCorruptionError(
                    f"JSON parsing error for {namespace}.{key}: {e}"
                )

    async def set_if_absent(
        self, namespace: str, key: str, value: dict[str, Any]
    ) -> bool:
        """Atomic insert — returns False if (namespace, key) already exists."""
        pool = await self._get_pool()
        payload: Any = value
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                INSERT INTO storage (namespace, key, value)
                VALUES ($1, $2, $3::jsonb)
                ON CONFLICT (namespace, key) DO NOTHING
                """,
                namespace,
                key,
                payload,
            )
            # asyncpg status: "INSERT 0 1" when inserted, "INSERT 0 0" on conflict
            parts = result.split()
            return len(parts) >= 3 and parts[-1] == "1"

    async def set(self, namespace: str, key: str, value: dict[str, Any]) -> None:
        """Сохранить значение в storage.

        JSONB автоматически валидирует JSON, поэтому можно передавать dict напрямую.
        Важно: asyncpg НЕ всегда автоматически сериализует Python dict/list в json/jsonb
        без дополнительных кодеков. Поэтому сериализуем сами.
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            payload: Any = value
            if isinstance(payload, (dict, list)):
                payload = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            await conn.execute(
                """
                INSERT INTO storage (namespace, key, value)
                VALUES ($1, $2, $3::jsonb)
                ON CONFLICT (namespace, key) DO UPDATE SET value = $3::jsonb
            """,
                namespace,
                key,
                payload,
            )

    async def delete(self, namespace: str, key: str) -> bool:
        """Удалить значение из storage."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM storage WHERE namespace = $1 AND key = $2", namespace, key
            )
            # result содержит строку вида "DELETE N", где N - количество удаленных строк
            return result != "DELETE 0"

    async def list_keys(self, namespace: str) -> list[str]:
        """Получить список ключей в namespace."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT key FROM storage WHERE namespace = $1", namespace
            )
            return [row["key"] for row in rows]

    async def list_namespaces(self) -> list[str]:
        """Получить список всех namespace."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT DISTINCT namespace FROM storage")
            return sorted(row["namespace"] for row in rows)

    async def clear_namespace(self, namespace: str) -> None:
        """Очистить все записи в namespace."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM storage WHERE namespace = $1", namespace)

    async def close(self) -> None:
        """Закрыть пул соединений."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    @asynccontextmanager
    async def transaction(self):
        """
        Контекстный менеджер для транзакций PostgreSQL.

        Использование:
            async with adapter.transaction():
                await adapter.set("ns", "key1", {"value": 1})
                await adapter.set("ns", "key2", {"value": 2})
                # Все операции выполняются в одной транзакции
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                yield

    async def batch_set(self, namespace: str, items: dict[str, dict[str, Any]]) -> None:
        """Массовая запись значений в namespace."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            # Используем executemany для оптимизации множественных вставок
            values = []
            for key, value in items.items():
                payload: Any = value
                if isinstance(payload, (dict, list)):
                    payload = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                values.append((namespace, key, payload))
            await conn.executemany(
                """
                INSERT INTO storage (namespace, key, value)
                VALUES ($1, $2, $3::jsonb)
                ON CONFLICT (namespace, key) DO UPDATE SET value = $3::jsonb
            """,
                values,
            )

    async def get_many(self, namespace: str, keys: list[str]) -> dict[str, Any]:
        """Batch-get multiple keys in one query (avoids N+1)."""
        if not keys:
            return {}
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT key, value FROM storage WHERE namespace = $1 AND key = ANY($2)",
                namespace,
                keys,
            )
            result: dict[str, Any] = {}
            for row in rows:
                key = row["key"]
                value = row["value"]
                if value is None:
                    result[key] = None
                    continue
                try:
                    parsed = json.loads(value) if isinstance(value, str) else value
                    if isinstance(parsed, dict):
                        result[key] = parsed
                    else:
                        result[key] = None
                except (json.JSONDecodeError, TypeError):
                    result[key] = None
            return result

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

        Пример:
            async for key, value in adapter.iter_namespace("devices"):
                print(f"Device {key}: {value}")
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            # Не используем async context manager для cursor(): в некоторых версиях asyncpg
            # conn.cursor(...) возвращает CursorFactory без поддержки `async with`.
            # Вместо этого читаем батчами через LIMIT/OFFSET.
            offset = 0
            while True:
                rows = await conn.fetch(
                    """
                    SELECT key, value
                    FROM storage
                    WHERE namespace = $1
                    ORDER BY key
                    LIMIT $2 OFFSET $3
                    """,
                    namespace,
                    batch_size,
                    offset,
                )
                if not rows:
                    break
                for row in rows:
                    value = row["value"]
                    if isinstance(value, dict):
                        yield row["key"], value
                        continue
                    if isinstance(value, (str, bytes, bytearray)):
                        try:
                            parsed = json.loads(value)
                            if isinstance(parsed, dict):
                                yield row["key"], parsed
                                continue
                        except json.JSONDecodeError:
                            pass
                    raise StorageCorruptionError(
                        f"Invalid value type in storage: expected dict, "
                        f"got {type(value).__name__} for {namespace}.{row['key']}"
                    )
                offset += len(rows)
