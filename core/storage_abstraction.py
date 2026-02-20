"""
Абстракция хранилища для Core (Dependency Inversion).

Core зависит только от этого Protocol, а не от конкретных адаптеров (SQLite, PostgreSQL).
Реализации адаптеров живут в слое adapters и подставляются снаружи.
"""

from __future__ import annotations

from typing import Any, Optional, AsyncIterator, Protocol


class IStorageBackend(Protocol):
    """
    Протокол бэкенда хранилища: namespace + key + JSON value.

    Соответствует контракту adapters.storage_adapter.StorageAdapter.
    Реализации (SQLiteAdapter, PostgreSQLAdapter) предоставляются слоем adapters.
    """

    async def get(self, namespace: str, key: str) -> Optional[dict[str, Any]]:
        """Получить значение по ключу из namespace."""
        ...

    async def set(self, namespace: str, key: str, value: dict[str, Any]) -> None:
        """Сохранить значение по ключу в namespace."""
        ...

    async def delete(self, namespace: str, key: str) -> bool:
        """Удалить значение по ключу из namespace."""
        ...

    async def list_keys(self, namespace: str) -> list[str]:
        """Получить список всех ключей в namespace."""
        ...

    async def list_namespaces(self) -> list[str]:
        """Получить список всех namespace в хранилище."""
        ...

    async def clear_namespace(self, namespace: str) -> None:
        """Очистить все записи в namespace."""
        ...

    async def close(self) -> None:
        """Закрыть соединение с хранилищем."""
        ...

    def transaction(self) -> Any:
        """Контекстный менеджер для транзакций (async with)."""
        ...

    async def batch_set(
        self, namespace: str, items: dict[str, dict[str, Any]]
    ) -> None:
        """Массовая запись значений в namespace."""
        ...

    def iter_namespace(
        self, namespace: str, batch_size: int = 100
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Итерировать по ключам в namespace батчами."""
        ...
