"""
Plugin isolation primitives.

SECURITY P0:
- Plugins must not get direct access to runtime storage/services.
- Isolation is enforced via small proxy wrappers that are safe to use from core.

This module lives in `core` on purpose: it contains no app/module dependencies and
can be used by the kernel/runtime as a safe default.
"""

from __future__ import annotations

from typing import Any, List, Optional

from core.exceptions import ForbiddenError


DEFAULT_ALLOWED_SERVICES = [
    "logger.log",
    "logger.info",
    "logger.warning",
    "logger.error",
    "logger.debug",
]


class StorageProxy:
    """
    Proxy for isolating plugins from direct storage access.

    - Plugin can only see its own namespace.
    - Keys are automatically prefixed with "<namespace>:".
    - Admin-style operations are forbidden.
    """

    def __init__(self, storage: Any, namespace: str):
        if not namespace or ":" in namespace:
            raise ValueError(f"Invalid namespace: {namespace}")

        self._storage = storage
        self._namespace = namespace

    def _make_key(self, key: str) -> str:
        if ":" in key:
            raise ForbiddenError(f"Key cannot contain ':' separator: {key}")
        return f"{self._namespace}:{key}"

    async def get(self, key: str, default: Any = None) -> Any:
        namespaced_key = self._make_key(key)
        return await self._storage.get(namespaced_key, default)

    async def put(self, key: str, value: Any) -> None:
        namespaced_key = self._make_key(key)
        await self._storage.put(namespaced_key, value)

    async def delete(self, key: str) -> None:
        namespaced_key = self._make_key(key)
        await self._storage.delete(namespaced_key)

    async def exists(self, key: str) -> bool:
        namespaced_key = self._make_key(key)
        return await self._storage.exists(namespaced_key)

    async def keys(self, pattern: Optional[str] = None) -> List[str]:
        namespace_pattern = f"{self._namespace}:*"
        all_keys = await self._storage.keys(namespace_pattern)
        prefix_len = len(self._namespace) + 1
        result = [key[prefix_len:] for key in all_keys]
        if pattern:
            import fnmatch

            result = [key for key in result if fnmatch.fnmatch(key, pattern)]
        return result

    async def clear(self) -> None:
        keys = await self.keys()
        for key in keys:
            await self.delete(key)

    async def list_all(self) -> List[str]:
        raise ForbiddenError("StorageProxy: list_all() is forbidden for plugins")

    async def clear_all(self) -> None:
        raise ForbiddenError("StorageProxy: clear_all() is forbidden for plugins")


class ServiceProxy:
    """
    Proxy for limiting plugin access to services.
    """

    def __init__(self, service_registry: Any, allowed_services: List[str], plugin_name: str):
        self._service_registry = service_registry
        self._allowed_services = set(allowed_services)
        self._plugin_name = plugin_name

    def _is_allowed(self, service_name: str) -> bool:
        if service_name in self._allowed_services:
            return True
        for pattern in self._allowed_services:
            if pattern.endswith(".*"):
                prefix = pattern[:-2]
                if service_name.startswith(f"{prefix}."):
                    return True
        return False

    async def call(self, service_name: str, **kwargs) -> Any:
        if not self._is_allowed(service_name):
            raise ForbiddenError(
                f"Plugin '{self._plugin_name}' is not allowed to call service '{service_name}'"
            )
        return await self._service_registry.call(service_name, **kwargs)

    async def has_service(self, service_name: str) -> bool:
        if not self._is_allowed(service_name):
            return False
        return await self._service_registry.has_service(service_name)

