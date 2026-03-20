"""
Storage Proxy - изоляция плагинов от прямого доступа к storage.

SECURITY P0: Плагины НЕ должны иметь прямой доступ к runtime.storage.
Каждый плагин видит только свой namespace через StorageProxy.

Архитектура:
- Каждый плагин получает StorageProxy с namespace=plugin_name
- StorageProxy автоматически добавляет prefix ко всем ключам
- Плагин физически не может прочитать данные другого плагина
- Админские операции (list_all, clear_all) запрещены для плагинов

Пример:
    # В plugin_manager при загрузке плагина:
    proxy = StorageProxy(runtime.storage, namespace="oauth_yandex")
    plugin.storage = proxy
    
    # В плагине:
    await self.storage.put("tokens", {"access": "..."})
    # Реально сохраняется как "oauth_yandex:tokens"
    
    # Плагин НЕ может:
    await self.storage.put("oauth_google:tokens", ...)  # Forbidden
    await self.storage.get("oauth_google:tokens")        # Forbidden
"""

from typing import Any, List, Optional
from core.errors import ForbiddenError


DEFAULT_ALLOWED_SERVICES = [
    "logger.log",
    "logger.info",
    "logger.warning",
    "logger.error",
    "logger.debug",
]


class StorageProxy:
    """
    Proxy для изоляции плагинов от прямого доступа к storage.
    
    SECURITY P0:
    - Плагин видит только свой namespace
    - Все ключи автоматически prefixed
    - Нет способа получить данные другого плагина
    - Админские операции запрещены
    
    Attributes:
        _storage: Реальный storage backend
        _namespace: Namespace плагина (обычно plugin_name)
    """
    
    def __init__(self, storage: Any, namespace: str):
        """
        Initialize StorageProxy.
        
        Args:
            storage: Real storage backend (CoreStorage)
            namespace: Plugin namespace (e.g., "oauth_yandex")
            
        Raises:
            ValueError: If namespace is invalid
        """
        if not namespace or ":" in namespace:
            raise ValueError(f"Invalid namespace: {namespace}")
        
        self._storage = storage
        self._namespace = namespace
    
    def _make_key(self, key: str) -> str:
        """
        Make namespaced key.
        
        Args:
            key: User-provided key
            
        Returns:
            Namespaced key (e.g., "oauth_yandex:tokens")
            
        Raises:
            ForbiddenError: If key tries to escape namespace
        """
        if ":" in key:
            raise ForbiddenError(f"Key cannot contain ':' separator: {key}")
        
        return f"{self._namespace}:{key}"
    
    async def get(self, key: str, default: Any = None) -> Any:
        """Get value from storage."""
        namespaced_key = self._make_key(key)
        return await self._storage.get(namespaced_key, default)
    
    async def put(self, key: str, value: Any) -> None:
        """Put value to storage."""
        namespaced_key = self._make_key(key)
        await self._storage.put(namespaced_key, value)
    
    async def delete(self, key: str) -> None:
        """Delete key from storage."""
        namespaced_key = self._make_key(key)
        await self._storage.delete(namespaced_key)
    
    async def exists(self, key: str) -> bool:
        """Check if key exists."""
        namespaced_key = self._make_key(key)
        return await self._storage.exists(namespaced_key)
    
    async def keys(self, pattern: Optional[str] = None) -> List[str]:
        """List keys in plugin namespace."""
        namespace_pattern = f"{self._namespace}:*"
        all_keys = await self._storage.keys(namespace_pattern)
        prefix_len = len(self._namespace) + 1
        result = [key[prefix_len:] for key in all_keys]
        if pattern:
            import fnmatch
            result = [key for key in result if fnmatch.fnmatch(key, pattern)]
        return result
    
    async def clear(self) -> None:
        """Clear all keys in plugin namespace."""
        keys = await self.keys()
        for key in keys:
            await self.delete(key)
    
    async def list_all(self) -> List[str]:
        """FORBIDDEN: Plugins cannot list all storage keys."""
        raise ForbiddenError("StorageProxy: list_all() is forbidden for plugins")
    
    async def clear_all(self) -> None:
        """FORBIDDEN: Plugins cannot clear all storage."""
        raise ForbiddenError("StorageProxy: clear_all() is forbidden for plugins")


class ServiceProxy:
    """
    Proxy для ограничения доступа плагинов к сервисам.
    
    SECURITY P0:
    - Плагин может вызывать только разрешенные сервисы
    - Нет доступа к admin-only сервисам
    - Нет доступа к внутренним сервисам других плагинов
    
    Attributes:
        _service_registry: ServiceRegistry runtime
        _allowed_services: Set of allowed service names
        _plugin_name: Name of plugin (for logging)
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
        return await self._service_registry.has(service_name)
