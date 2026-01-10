"""
StorageWithStateMirror - обёртка для синхронизации Storage и StateEngine.

Обеспечивает консистентность между persistent storage (source of truth)
и in-memory state_engine (read-only cache).
"""

from typing import Any

from core.storage import Storage
from core.state_engine import StateEngine


class StorageWithStateMirror:
    """
    Обёртка для Storage, которая автоматически синхронизирует изменения
    с StateEngine.
    
    Формат ключей в state_engine: f"{namespace}.{key}"
    
    Гарантирует консистентность: если операция с storage падает,
    state_engine не обновляется.
    """
    
    def __init__(self, storage: Storage, state_engine: StateEngine):
        """
        Инициализация обёртки.
        
        Args:
            storage: экземпляр Storage (source of truth)
            state_engine: экземпляр StateEngine (read-only cache)
        """
        self._storage = storage
        self._state_engine = state_engine

    async def get(self, namespace: str, key: str) -> Any:
        """
        Получить значение из storage.
        
        Args:
            namespace: пространство имён
            key: ключ
            
        Returns:
            Значение из storage
        """
        return await self._storage.get(namespace, key)

    async def set(self, namespace: str, key: str, value: Any) -> None:
        """
        Сохранить значение в storage и синхронизировать с state_engine.
        
        Гарантирует консистентность: если storage.set() падает,
        state_engine не обновляется.
        
        Args:
            namespace: пространство имён
            key: ключ
            value: значение для сохранения
        """
        state_key = f"{namespace}.{key}"
        try:
            # Сначала сохраняем в storage (source of truth)
            await self._storage.set(namespace, key, value)
            # Только после успешного сохранения обновляем state_engine
            await self._state_engine.set(state_key, value)
        except Exception:
            # Если storage.set() упал, откатываем state_engine (если был обновлён)
            try:
                await self._state_engine.delete(state_key)
            except Exception:
                pass
            # Пробрасываем оригинальную ошибку
            raise

    async def delete(self, namespace: str, key: str) -> bool:
        """
        Удалить значение из storage и state_engine.
        
        Гарантирует консистентность: если storage.delete() падает,
        state_engine не обновляется.
        
        Args:
            namespace: пространство имён
            key: ключ
            
        Returns:
            True если запись была удалена
        """
        state_key = f"{namespace}.{key}"
        try:
            # Сначала удаляем из storage
            res = await self._storage.delete(namespace, key)
            # Только после успешного удаления обновляем state_engine
            if res:
                await self._state_engine.delete(state_key)
            return res
        except Exception:
            # Если storage.delete() упал, state_engine остаётся без изменений
            # Пробрасываем оригинальную ошибку
            raise

    async def list_keys(self, namespace: str) -> list[str]:
        """
        Получить список всех ключей в namespace.
        
        Args:
            namespace: пространство имён
            
        Returns:
            Список ключей
        """
        return await self._storage.list_keys(namespace)

    async def clear_namespace(self, namespace: str) -> None:
        """
        Очистить все записи в namespace.
        
        Args:
            namespace: пространство имён
        """
        return await self._storage.clear_namespace(namespace)

    async def close(self) -> None:
        """Закрыть соединение с storage."""
        return await self._storage.close()
