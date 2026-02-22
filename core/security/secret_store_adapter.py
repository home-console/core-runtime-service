"""
Adapter: IStorageBackend (namespace+key) -> flat key API for SecretStore.

SecretStore expects get_async(key), set_async(key, value), list_keys_async(pattern), delete_async(key).
This wrapper maps keys like "secrets.store.xxx" to namespace "secrets.store", key "xxx".
"""

from __future__ import annotations

from typing import Any, Optional

from core.storage_abstraction import IStorageBackend

SECRETS_NS = "secrets.store"
PREFIX = "secrets.store."


class SecretStoreStorageAdapter:
    """
    Wraps IStorageBackend and exposes flat key API for SecretStore.
    Keys are "secrets.store.<key>"; stored as namespace "secrets.store", key "<key>".
    Values are stored as dict {"_v": value_str} so backend (dict-only) is satisfied.
    """

    def __init__(self, backend: IStorageBackend) -> None:
        self._backend = backend

    def _ns_key(self, full_key: str) -> tuple[str, str]:
        if full_key.startswith(PREFIX):
            return SECRETS_NS, full_key[len(PREFIX) :]
        return SECRETS_NS, full_key

    async def get_async(self, key: str) -> Optional[str]:
        ns, k = self._ns_key(key)
        val = await self._backend.get(ns, k)
        if val is None:
            return None
        if isinstance(val, dict) and "_v" in val:
            return val["_v"]
        if isinstance(val, dict):
            import json
            return json.dumps(val)
        return str(val)

    async def set_async(self, key: str, value: str) -> None:
        ns, k = self._ns_key(key)
        await self._backend.set(ns, k, {"_v": value})

    async def delete_async(self, key: str) -> bool:
        ns, k = self._ns_key(key)
        return await self._backend.delete(ns, k)

    async def list_keys_async(self, pattern: str) -> list[str]:
        if not pattern.startswith(SECRETS_NS) or "*" not in pattern:
            return []
        keys = await self._backend.list_keys(SECRETS_NS)
        return [f"{PREFIX}{k}" for k in keys]
