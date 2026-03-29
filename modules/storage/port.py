"""
Storage Ports - абстракции для доступа к storage из ядра.

CoreStoragePort - единый интерфейс для core storage (для CoreRuntime).
VaultStoragePort - интерфейс для vault storage (если dual-mode).
StorageStack - результат сборки стека (manager, core_port, vault_port).

Создание конкретных адаптеров и сборка стека — в слое adapters (storage_factory).
"""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional

from core.runtime.state_engine import StateEngine
from modules.storage.abstraction import IStorageBackend
from modules.storage.manager import StorageManager
from modules.storage.mirror import StorageWithStateMirror
from modules.storage.storage import Storage


class CoreStoragePort:
    """
    Порт для доступа к core storage из ядра.

    Оборачивает StorageAdapter в Storage + StorageWithStateMirror
    для синхронизации с StateEngine.

    Используется CoreRuntime как единая точка доступа к storage.
    """

    def __init__(self, adapter: IStorageBackend, state_engine: StateEngine):
        """
        Инициализация порта.

        Args:
            adapter: StorageAdapter для core storage
            state_engine: StateEngine для синхронизации состояния
        """
        self._adapter = adapter
        base_storage = Storage(adapter)
        self._storage = StorageWithStateMirror(base_storage, state_engine)

    @property
    def storage(self) -> StorageWithStateMirror:
        """Получить StorageWithStateMirror для использования в runtime."""
        return self._storage

    # Делегируем все методы Storage API
    async def get(self, namespace: str, key: str) -> Optional[dict[str, Any]]:
        """Получить значение."""
        return await self._storage.get(namespace, key)

    async def set(self, namespace: str, key: str, value: dict[str, Any]) -> None:
        """Сохранить значение."""
        await self._storage.set(namespace, key, value)

    async def delete(self, namespace: str, key: str) -> bool:
        """Удалить значение."""
        return await self._storage.delete(namespace, key)

    async def list_keys(self, namespace: str) -> list[str]:
        """Получить список ключей в namespace."""
        return await self._storage.list_keys(namespace)

    async def list_namespaces(self) -> list[str]:
        """Получить список всех namespace."""
        return await self._storage.list_namespaces()

    async def clear_namespace(self, namespace: str) -> None:
        """Очистить namespace."""
        await self._storage.clear_namespace(namespace)

    async def close(self) -> None:
        """Закрыть соединение."""
        await self._storage.close()

    @property
    def closed(self) -> bool:
        """Проверить, закрыт ли адаптер."""
        return getattr(self._adapter, "closed", False)

    @asynccontextmanager
    async def transaction(self):
        """Контекстный менеджер для транзакций."""
        async with self._storage.transaction():
            yield

    async def iter_namespace(
        self, namespace: str, batch_size: int = 100
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Итерировать по namespace."""
        async for item in self._storage.iter_namespace(namespace, batch_size):
            yield item


class VaultStoragePort:
    """
    Порт для доступа к vault storage (dual-mode).

    Оборачивает SecureStorageWrapper для безопасного доступа к vault.
    Используется для хранения секретов и критичных данных.
    """

    def __init__(self, secure_storage):
        """
        Инициализация порта.

        Args:
            secure_storage: SecureStorageWrapper для vault storage
        """
        self._secure_storage = secure_storage

    async def get(self, namespace: str, key: str) -> Optional[dict[str, Any]]:
        """Получить значение из vault."""
        return await self._secure_storage.get(namespace, key)

    async def secure_set(self, namespace: str, key: str, value: dict[str, Any]) -> None:
        """
        Безопасная запись в vault (с epoch bump, audit log, Merkle root).

        Используется для критичных namespace:
        - secrets.store
        - agent.private_keys
        - oauth.tokens
        - и т.д.
        """
        await self._secure_storage.secure_set(namespace, key, value)

    async def secure_delete(self, namespace: str, key: str) -> bool:
        """Безопасное удаление из vault."""
        return await self._secure_storage.secure_delete(namespace, key)

    async def list_keys(self, namespace: str) -> list[str]:
        """Получить список ключей в namespace."""
        return await self._secure_storage.list_keys(namespace)

    async def list_namespaces(self) -> list[str]:
        """Получить список всех namespace."""
        return await self._secure_storage.list_namespaces()

    async def close(self) -> None:
        """Закрыть соединение."""
        await self._secure_storage.close()

    @asynccontextmanager
    async def transaction(self):
        """Контекстный менеджер для транзакций."""
        async with self._secure_storage.transaction():
            yield

    async def iter_namespace(
        self, namespace: str, batch_size: int = 100
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Итерировать по namespace."""
        async for item in self._secure_storage.iter_namespace(namespace, batch_size):
            yield item


@dataclass
class StorageStack:
    """
    Полный стек storage компонентов для ядра.

    Собирается в слое adapters (build_storage_stack).
    """

    manager: StorageManager
    core_port: CoreStoragePort
    vault_port: Optional[VaultStoragePort] = None
