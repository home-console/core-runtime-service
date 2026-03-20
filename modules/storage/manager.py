"""
Storage v3 Manager — Orchestrates Core and Vault storage isolation.

Provides:
- Dual-mode initialization (separate adapters for core and vault)
- Namespace enforcement (prevent vault writes through core storage)
- Backward compatibility (single-mode fallback)
- Security invariants enforcement
"""

from typing import List, Optional

from modules.storage.abstraction import IStorageBackend
from modules.storage.errors import NamespaceViolationError, StorageConfigurationError

# Critical vault namespaces that MUST NOT be written through core_storage in dual mode
CRITICAL_VAULT_NAMESPACES = [
    "secrets.store",
    "agent.private_keys",
    "agent.enrollment",
    "oauth.tokens",
    "ssh.credentials",
    "vault",
]


class StorageManager:
    """
    Manages Core and Vault storage isolation (Storage v3).

    Modes:
    - single: one adapter handles all namespaces (backward compatible)
    - dual: separate core_storage and vault_storage with namespace enforcement

    Properties:
    - If vault_storage is None (single mode), use core_storage for everything
    - If vault_storage exists (dual mode), enforce namespace segregation
    - Vault namespaces MUST go through vault_storage only
    """

    def __init__(
        self,
        core_storage: IStorageBackend,
        vault_storage: Optional[IStorageBackend] = None,
        mode: str = "single",
    ):
        """
        Initialize StorageManager.

        Args:
            core_storage: Storage adapter for core operations
            vault_storage: Optional separate storage for vault (enables dual mode)
            mode: "single" or "dual"

        Raises:
            StorageConfigurationError: If mode == "dual" and vault_storage is None
        """
        self._core_storage = core_storage
        self._vault_storage = vault_storage
        self._mode = mode

        # Validate configuration
        if mode == "dual" and vault_storage is None:
            raise StorageConfigurationError(
                "Dual mode requires vault_storage; got None"
            )

        if mode not in ("single", "dual"):
            raise StorageConfigurationError(
                f"Invalid mode: {mode}; must be 'single' or 'dual'"
            )

    @property
    def mode(self) -> str:
        """Get current storage mode."""
        return self._mode

    @property
    def is_dual_mode(self) -> bool:
        """Check if in dual mode."""
        return self._mode == "dual"

    def get_core(self) -> IStorageBackend:
        """Get core storage adapter (read-only for vault namespaces)."""
        return self._core_storage

    def get_vault(self) -> IStorageBackend:
        """
        Get vault storage adapter.

        Returns:
            vault_storage if in dual mode, otherwise core_storage (backward compatible)
        """
        if self.is_dual_mode:
            return self._vault_storage
        return self._core_storage

    async def set(
        self, namespace: str, key: str, value: dict, target: str = "auto"
    ) -> None:
        """
        Set value, routing to correct storage based on namespace.

        Args:
            namespace: Namespace (checked against CRITICAL_VAULT_NAMESPACES)
            key: Key within namespace
            value: Value to store
            target: "auto" (automatic routing), "core", or "vault"

        Raises:
            NamespaceViolationError: If vault namespace forced to core in dual mode
        """
        # Explicit routing
        if target == "core":
            # Check namespace safety
            if self.is_dual_mode and self._is_vault_namespace(namespace):
                raise NamespaceViolationError(
                    f"Cannot write vault namespace '{namespace}' to core storage in dual mode; "
                    f"use target='vault' instead"
                )
            await self._core_storage.set(namespace, key, value)
            return

        if target == "vault":
            # Vault storage only available in dual mode
            if not self.is_dual_mode:
                raise StorageConfigurationError(
                    "target='vault' only available in dual mode; use target='auto' for single mode"
                )
            await self._vault_storage.set(namespace, key, value)
            return

        # Auto-routing based on namespace
        if self.is_dual_mode and self._is_vault_namespace(namespace):
            await self._vault_storage.set(namespace, key, value)
        else:
            await self._core_storage.set(namespace, key, value)

    async def get(
        self, namespace: str, key: str, target: str = "auto"
    ) -> Optional[dict]:
        """
        Get value from appropriate storage.

        Args:
            namespace: Namespace
            key: Key within namespace
            target: "auto", "core", or "vault"

        Returns:
            Value or None if not found
        """
        if target == "core":
            return await self._core_storage.get(namespace, key)

        if target == "vault":
            if not self.is_dual_mode:
                raise StorageConfigurationError(
                    "target='vault' only available in dual mode"
                )
            return await self._vault_storage.get(namespace, key)

        # Auto-routing
        if self.is_dual_mode and self._is_vault_namespace(namespace):
            return await self._vault_storage.get(namespace, key)
        else:
            return await self._core_storage.get(namespace, key)

    async def delete(self, namespace: str, key: str, target: str = "auto") -> bool:
        """
        Delete value from appropriate storage.

        Args:
            namespace: Namespace
            key: Key within namespace
            target: "auto", "core", or "vault"

        Returns:
            True if deleted, False if not found
        """
        if target == "core":
            if self.is_dual_mode and self._is_vault_namespace(namespace):
                raise NamespaceViolationError(
                    f"Cannot delete vault namespace '{namespace}' from core storage in dual mode"
                )
            return await self._core_storage.delete(namespace, key)

        if target == "vault":
            if not self.is_dual_mode:
                raise StorageConfigurationError(
                    "target='vault' only available in dual mode"
                )
            return await self._vault_storage.delete(namespace, key)

        # Auto-routing
        if self.is_dual_mode and self._is_vault_namespace(namespace):
            return await self._vault_storage.delete(namespace, key)
        else:
            return await self._core_storage.delete(namespace, key)

    async def list_keys(self, namespace: str, target: str = "auto") -> List[str]:
        """List keys in namespace."""
        if target == "core":
            return await self._core_storage.list_keys(namespace)
        if target == "vault":
            if not self.is_dual_mode:
                raise StorageConfigurationError(
                    "target='vault' only available in dual mode"
                )
            return await self._vault_storage.list_keys(namespace)

        if self.is_dual_mode and self._is_vault_namespace(namespace):
            return await self._vault_storage.list_keys(namespace)
        else:
            return await self._core_storage.list_keys(namespace)

    async def list_namespaces(self, target: str = "auto") -> List[str]:
        """List all namespaces."""
        if target == "core":
            return await self._core_storage.list_namespaces()
        if target == "vault":
            if not self.is_dual_mode:
                raise StorageConfigurationError(
                    "target='vault' only available in dual mode"
                )
            return await self._vault_storage.list_namespaces()

        if self.is_dual_mode:
            # Combine namespaces from both
            core_ns = await self._core_storage.list_namespaces()
            vault_ns = await self._vault_storage.list_namespaces()
            return sorted(set(core_ns + vault_ns))
        else:
            return await self._core_storage.list_namespaces()

    async def clear_namespace(self, namespace: str, target: str = "auto") -> None:
        """Clear all keys in namespace."""
        if target == "core":
            if self.is_dual_mode and self._is_vault_namespace(namespace):
                raise NamespaceViolationError(
                    f"Cannot clear vault namespace '{namespace}' from core storage in dual mode"
                )
            await self._core_storage.clear_namespace(namespace)
            return

        if target == "vault":
            if not self.is_dual_mode:
                raise StorageConfigurationError(
                    "target='vault' only available in dual mode"
                )
            await self._vault_storage.clear_namespace(namespace)
            return

        # Auto-routing
        if self.is_dual_mode and self._is_vault_namespace(namespace):
            await self._vault_storage.clear_namespace(namespace)
        else:
            await self._core_storage.clear_namespace(namespace)

    async def close(self) -> None:
        """Close both storage adapters."""
        await self._core_storage.close()
        if self.is_dual_mode:
            await self._vault_storage.close()

    @staticmethod
    def _is_vault_namespace(namespace: str) -> bool:
        """Check if namespace is in vault critical list."""
        # Exact match or starts with a vault namespace prefix
        for vault_ns in CRITICAL_VAULT_NAMESPACES:
            if namespace == vault_ns or namespace.startswith(vault_ns + "."):
                return True
        return False

    def get_vault_namespaces(self) -> List[str]:
        """Get list of critical vault namespaces."""
        return list(CRITICAL_VAULT_NAMESPACES)
