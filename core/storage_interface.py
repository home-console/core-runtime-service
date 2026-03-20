"""
Core Storage Port - интерфейс для абстракции хранилища.

Позволяет разорвать циклические зависимости между storage_manager,
storage_mirror, storage_port и другими модулями.
"""

from typing import Protocol, runtime_checkable, Any, Dict, Optional, List


@runtime_checkable
class IStorageAdapter(Protocol):
    """
    Interface for storage backend implementation (SQLite, PostgreSQL, etc).
    
    Enables dependency inversion and swappable storage adapters.
    """
    
    async def init_storage(self) -> None:
        """Initialize storage backend."""
        ...

    async def set(
        self,
        namespace: str,
        key: str,
        value: Any
    ) -> None:
        """Set value in storage."""
        ...

    async def get(
        self,
        namespace: str,
        key: str
    ) -> Optional[Any]:
        """Get value from storage."""
        ...

    async def delete(
        self,
        namespace: str,
        key: str
    ) -> None:
        """Delete value from storage."""
        ...

    async def list_keys(
        self,
        namespace: str,
        prefix: Optional[str] = None
    ) -> List[str]:
        """List keys in namespace."""
        ...


@runtime_checkable
class IStorageManager(Protocol):
    """
    Interface for storage management (transactions, migrations, etc).
    
    Coordinates between adapters and high-level operations.
    """
    
    async def init(self) -> None:
        """Initialize storage manager and all adapters."""
        ...

    async def set(
        self,
        namespace: str,
        key: str,
        value: Any
    ) -> None:
        """Set value with mutation tracking."""
        ...

    async def get(
        self,
        namespace: str,
        key: str
    ) -> Optional[Any]:
        """Get value."""
        ...

    async def migrate_storage(
        self,
        from_version: str,
        to_version: str
    ) -> None:
        """Migrate storage schema/data."""
        ...
