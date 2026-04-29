"""
EventBus factory — выбор реализации по конфигурации.

Использование:
    bus = create_event_bus(config, storage=storage_port.storage)
"""

from __future__ import annotations

import os
from typing import Any

from core.ports import IEventBus


def create_event_bus(config: Any = None, storage: Any = None) -> IEventBus:
    """
    Создать EventBus по конфигурации.

    Переменные окружения:
        EVENT_BUS_BACKEND=memory|redis (default: memory)
        REDIS_URL=redis://localhost:6379
    """
    backend = os.getenv("EVENT_BUS_BACKEND", "memory").lower().strip()

    if backend == "redis":
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379").strip()
        from core.messaging_redis import RedisStreamsEventBus

        return RedisStreamsEventBus(redis_url=redis_url, storage=storage)

    # default: in-memory
    from core.messaging import InMemoryEventBus

    return InMemoryEventBus(storage=storage)

