"""
EventBus Claim Manager — управление claim-lease для событий.

Отвечает за:
- Claim события worker'ом
- Lease TTL management
- Atomic claim operations для SQLite/PostgreSQL

Выделено из InMemoryEventBus для соблюдения SRP.
"""

import inspect
import time
from typing import Any, cast


class EventBusClaimManager:
    """
    Менеджер claim-lease для EventBus.

    Управляет блокировкой событий для обработки.
    """

    def __init__(self, storage: Any | None = None):
        """
        Инициализация менеджера.

        Args:
            storage: storage adapter для claim operations
        """
        self._storage = storage

    async def claim_event(self, event_id: str, worker_id: str) -> bool:
        """
        Claim события для обработки.

        Args:
            event_id: ID события
            worker_id: ID worker'а который claim'ит событие

        Returns:
            True если успешно claim'или
        """
        if self._storage is None:
            return True

        adapter = getattr(self._storage, "_adapter", None)
        if adapter is None:
            return await self._claim_event_fallback(event_id, worker_id)

        # Prefer feature detection over adapter name heuristics:
        # - SQLite adapters provide run_atomic(sync_fn)
        # - PostgreSQL adapters provide _get_pool() returning an async pool
        if callable(getattr(adapter, "run_atomic", None)):
            return await self._claim_event_sqlite_atomic(adapter, event_id, worker_id)

        if callable(getattr(adapter, "_get_pool", None)):
            return await self._claim_event_postgresql_atomic(adapter, event_id, worker_id)

        return await self._claim_event_fallback(event_id, worker_id)

    async def _claim_event_sqlite_atomic(
        self, adapter: Any, event_id: str, worker_id: str
    ) -> bool:
        """Atomic claim для SQLite."""
        run_atomic = getattr(adapter, "run_atomic", None)
        if not callable(run_atomic):
            return False

        now = time.time()

        def _sync_claim(conn: Any, _adapter: Any) -> bool:
            cursor = conn.execute(
                """
                UPDATE storage
                SET value = json_set(
                    json_set(value, '$.claimed_by', ?),
                    '$.claimed_at', ?
                )
                WHERE namespace = ?
                  AND key = ?
                  AND COALESCE(json_extract(value, '$.processed'), 0) = 0
                  AND (
                        json_extract(value, '$.claimed_by') IS NULL
                     OR json_extract(value, '$.claimed_by') = ?
                     OR (
                            ? - COALESCE(json_extract(value, '$.claimed_at'), 0.0)
                          ) > COALESCE(json_extract(value, '$.claim_ttl'), 60.0)
                  )
                """,
                (
                    worker_id,
                    now,
                    "event_bus_events",
                    event_id,
                    worker_id,
                    now,
                ),
            )
            return cursor.rowcount > 0

        result = run_atomic(_sync_claim)
        return await result if inspect.isawaitable(result) else bool(result)

    async def _claim_event_postgresql_atomic(
        self, adapter: Any, event_id: str, worker_id: str
    ) -> bool:
        """Atomic claim для PostgreSQL."""
        get_pool = getattr(adapter, "_get_pool", None)
        if not callable(get_pool):
            return False

        pool = get_pool()
        pool_value = await pool if inspect.isawaitable(pool) else pool
        if pool_value is None:
            return False
        acquire = getattr(pool_value, "acquire", None)
        if not callable(acquire):
            return False
        acquire_any = cast(Any, acquire)

        now = time.time()
        async with acquire_any() as conn:
            row = await conn.fetchrow(
                """
                UPDATE storage
                SET value = jsonb_set(
                    jsonb_set(value, '{claimed_by}', to_jsonb($3::text), true),
                    '{claimed_at}',
                    to_jsonb($4::double precision),
                    true
                )
                WHERE namespace = $1
                  AND key = $2
                  AND COALESCE((value ->> 'processed')::boolean, false) = false
                  AND (
                        value ->> 'claimed_by' IS NULL
                     OR value ->> 'claimed_by' = $3
                     OR (
                            $4 - COALESCE((value ->> 'claimed_at')::double precision, 0.0)
                          ) > COALESCE((value ->> 'claim_ttl')::double precision, 60.0)
                  )
                RETURNING 1
                """,
                "event_bus_events",
                event_id,
                worker_id,
                now,
            )
            return row is not None

    async def _claim_event_fallback(self, event_id: str, worker_id: str) -> bool:
        """Fallback claim без атомарности."""
        get = getattr(self._storage, "get", None)
        save = getattr(self._storage, "set", None)
        if not callable(get) or not callable(save):
            return True

        raw_outcome = get("event_bus_events", event_id)
        raw = await raw_outcome if inspect.isawaitable(raw_outcome) else raw_outcome
        if not isinstance(raw, dict):
            return False

        now = time.time()
        if raw.get("processed", False):
            return False

        claimed_by = raw.get("claimed_by")
        if claimed_by is not None and claimed_by != worker_id:
            claimed_at = float(raw.get("claimed_at", 0.0))
            if now - claimed_at <= float(raw.get("claim_ttl", 60.0)):
                return False

        raw["claimed_by"] = worker_id
        raw["claimed_at"] = now
        save_outcome = save("event_bus_events", event_id, raw)
        if inspect.isawaitable(save_outcome):
            await save_outcome
        return True
