"""
Абстракция хранилища для Core (Dependency Inversion).

Core зависит только от этого Protocol, а не от конкретных адаптеров (SQLite, PostgreSQL).
Реализации адаптеров живут в слое adapters и подставляются снаружи.
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Coroutine, Optional, Protocol


class IStorageBackend(Protocol):
    """
    Протокол бэкенда хранилища: namespace + key + JSON value.

    Соответствует контракту adapters.storage_adapter.StorageAdapter.
    Реализации (SQLiteAdapter, PostgreSQLAdapter) предоставляются слоем adapters.
    """

    def get(
        self, namespace: str, key: str
    ) -> Coroutine[Any, Any, Optional[dict[str, Any]]]:
        """Получить значение по ключу из namespace."""
        ...

    def set(
        self, namespace: str, key: str, value: dict[str, Any]
    ) -> Coroutine[Any, Any, None]:
        """Сохранить значение по ключу в namespace."""
        ...

    def delete(self, namespace: str, key: str) -> Coroutine[Any, Any, bool]:
        """Удалить значение по ключу из namespace."""
        ...

    def list_keys(self, namespace: str) -> Coroutine[Any, Any, list[str]]:
        """Получить список всех ключей в namespace."""
        ...

    def list_namespaces(self) -> Coroutine[Any, Any, list[str]]:
        """Получить список всех namespace в хранилище."""
        ...

    def clear_namespace(self, namespace: str) -> Coroutine[Any, Any, None]:
        """Очистить все записи в namespace."""
        ...

    def close(self) -> Coroutine[Any, Any, None]:
        """Закрыть соединение с хранилищем."""
        ...

    def transaction(self) -> Any:
        """Контекстный менеджер для транзакций (async with)."""
        ...

    def batch_set(
        self, namespace: str, items: dict[str, dict[str, Any]]
    ) -> Coroutine[Any, Any, None]:
        """Массовая запись значений в namespace."""
        ...

    def iter_namespace(
        self, namespace: str, batch_size: int = 100
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Итерировать по ключам в namespace батчами."""
        ...

    def iter_namespaces(self) -> AsyncIterator[str]:
        """Итерировать по всем namespace в хранилище."""
        ...

    def initialize_schema(self) -> Coroutine[Any, Any, None]:
        """Инициализировать схему хранилища (создать таблицы и т.п.)."""
        ...
