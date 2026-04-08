"""
EventBus Storage Manager — управление персистентностью событий.

Отвечает за:
- Сохранение событий в storage
- Получение необработанных событий
- Mark events as processed

Выделено из InMemoryEventBus для соблюдения SRP.
"""

import inspect
import time
from typing import Any, Awaitable, List


class EventBusStorageManager:
    """
    Менеджер хранения событий EventBus.

    Управляет персистентностью событий в storage.
    """

    def __init__(self, storage: Any | None = None):
        """
        Инициализация менеджера.

        Args:
            storage: storage adapter для персистентности
        """
        self._storage = storage

    async def save_event(self, event_dict: dict[str, Any]) -> None:
        """
        Сохранить событие в storage.

        Args:
            event_dict: словарь с данными события
        """
        if self._storage is None:
            return

        event_id = event_dict.get("id", "")
        save = getattr(self._storage, "set", None)
        if not callable(save):
            return

        outcome = save("event_bus_events", event_id, event_dict)
        if inspect.isawaitable(outcome):
            await outcome

    async def get_unprocessed_events(self) -> list[dict[str, Any]]:
        """
        Получить все необработанные события.

        Returns:
            Список необработанных событий (отсортированных по времени)
        """
        if self._storage is None:
            return []

        list_keys = getattr(self._storage, "list_keys", None)
        get = getattr(self._storage, "get", None)
        if not callable(list_keys) or not callable(get):
            return []

        keys_outcome = list_keys("event_bus_events")
        keys_value = (
            await keys_outcome if inspect.isawaitable(keys_outcome) else keys_outcome
        )
        if not isinstance(keys_value, list):
            return []

        keys_list = [str(key) for key in keys_value]

        events: list[dict[str, Any]] = []
        for event_id in keys_list:
            raw_outcome = get("event_bus_events", event_id)
            raw = await raw_outcome if inspect.isawaitable(raw_outcome) else raw_outcome
            if not isinstance(raw, dict):
                continue
            if not raw.get("processed", False):
                events.append(raw)

        # Сортировка по времени создания
        events.sort(key=lambda item: item.get("created_at", 0))
        return events

    async def is_event_processed(self, event_id: str) -> bool:
        """
        Проверить, обработано ли событие.

        Args:
            event_id: ID события

        Returns:
            True если событие обработано
        """
        if self._storage is None:
            return False

        get = getattr(self._storage, "get", None)
        if not callable(get):
            return False

        raw_outcome = get("event_bus_events", event_id)
        raw = await raw_outcome if inspect.isawaitable(raw_outcome) else raw_outcome
        if not isinstance(raw, dict):
            return False

        return bool(raw.get("processed", False))

    async def mark_event_processed(self, event_id: str) -> None:
        """
        Пометить событие как обработанное.

        Args:
            event_id: ID события
        """
        if self._storage is None:
            return

        get = getattr(self._storage, "get", None)
        save = getattr(self._storage, "set", None)
        if not callable(get) or not callable(save):
            return

        raw_outcome = get("event_bus_events", event_id)
        raw = await raw_outcome if inspect.isawaitable(raw_outcome) else raw_outcome
        if not isinstance(raw, dict):
            return

        raw["processed"] = True
        raw["processed_at"] = time.time()
        raw["claimed_by"] = None
        raw["claimed_at"] = None

        save_outcome = save("event_bus_events", event_id, raw)
        if inspect.isawaitable(save_outcome):
            await save_outcome
