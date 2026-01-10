"""
PostgreSQL адаптер для Storage API.

Использует asyncpg для асинхронной работы с PostgreSQL.
Та же схема: namespace | key | value (JSON as TEXT).
"""

import json
from typing import Any, Optional
import asyncio

try:
    import asyncpg
    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False

from .storage_adapter import StorageAdapter


class PostgreSQLAdapter(StorageAdapter):
    """PostgreSQL адаптер для key-value хранилища с namespace.

    Использует asyncpg для асинхронной работы с PostgreSQL.
    Инициализация схемы не выполняется автоматически — отдельный метод
    `initialize_schema()` должен быть вызван явно.
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
        
        JSONB автоматически валидируется PostgreSQL, поэтому json.loads не нужен.
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT value FROM storage WHERE namespace = $1 AND key = $2",
                namespace, key
            )
            if row is None:
                return None
            # JSONB уже является dict в asyncpg, но для совместимости возвращаем как dict
            value = row["value"]
            if isinstance(value, dict):
                return value
            # Fallback на json.loads если по какой-то причине вернулся текст
            try:
                return json.loads(value) if isinstance(value, str) else value
            except (json.JSONDecodeError, ValueError) as e:
                # Логируем ошибку парсинга, но не падаем
                import sys
                print(
                    f"[PostgreSQLAdapter] Ошибка парсинга JSON для {namespace}.{key}: {e}",
                    file=sys.stderr
                )
                return None

    async def set(self, namespace: str, key: str, value: dict[str, Any]) -> None:
        """Сохранить значение в storage.
        
        JSONB автоматически валидирует JSON, поэтому можно передавать dict напрямую.
        asyncpg автоматически сериализует dict в JSONB.
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            # asyncpg автоматически сериализует dict в JSONB
            # Не нужно делать json.dumps() - asyncpg сделает это сам
            await conn.execute("""
                INSERT INTO storage (namespace, key, value)
                VALUES ($1, $2, $3::jsonb)
                ON CONFLICT (namespace, key) DO UPDATE SET value = $3::jsonb
            """, namespace, key, value)

    async def delete(self, namespace: str, key: str) -> bool:
        """Удалить значение из storage."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM storage WHERE namespace = $1 AND key = $2",
                namespace, key
            )
            # result содержит строку вида "DELETE N", где N - количество удаленных строк
            return result != "DELETE 0"

    async def list_keys(self, namespace: str) -> list[str]:
        """Получить список ключей в namespace."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT key FROM storage WHERE namespace = $1",
                namespace
            )
            return [row["key"] for row in rows]

    async def clear_namespace(self, namespace: str) -> None:
        """Очистить все записи в namespace."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM storage WHERE namespace = $1",
                namespace
            )

    async def close(self) -> None:
        """Закрыть пул соединений."""
        if self._pool:
            await self._pool.close()
            self._pool = None
