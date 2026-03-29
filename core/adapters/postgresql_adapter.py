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
from typing import Any, AsyncIterator, Optional

try:
    import asyncpg

    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False

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

        self._pool: Optional[asyncpg.Pool] = None

    async def _get_pool(self) -> asyncpg.Pool:
        """Создать или вернуть пул соединений."""
        if self._pool is None:
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

    async def set(self, namespace: str, key: str, value: dict[str, Any]) -> None:
        """Сохранить значение в storage.

        JSONB автоматически валидирует JSON, поэтому можно передавать dict напрямую.
        asyncpg автоматически сериализует dict в JSONB.
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            # asyncpg автоматически сериализует dict в JSONB
            # Не нужно делать json.dumps() - asyncpg сделает это сам
            await conn.execute(
                """
                INSERT INTO storage (namespace, key, value)
                VALUES ($1, $2, $3::jsonb)
                ON CONFLICT (namespace, key) DO UPDATE SET value = $3::jsonb
            """,
                namespace,
                key,
                value,
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
            # asyncpg автоматически сериализует dict в JSONB
            values = [(namespace, key, value) for key, value in items.items()]
            await conn.executemany(
                """
                INSERT INTO storage (namespace, key, value)
                VALUES ($1, $2, $3::jsonb)
                ON CONFLICT (namespace, key) DO UPDATE SET value = $3::jsonb
            """,
                values,
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

        Пример:
            async for key, value in adapter.iter_namespace("devices"):
                print(f"Device {key}: {value}")
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            # Используем cursor для efficient streaming больших наборов
            async with conn.cursor(
                """
                SELECT key, value FROM storage WHERE namespace = $1
            """,
                namespace,
            ) as cursor:
                while True:
                    rows = await cursor.fetch(batch_size)
                    if not rows:
                        break
                    for row in rows:
                        yield row["key"], row["value"]
