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
    proxy = StorageProxy(runtime.storage, namespace="oauth_provider")
    plugin.storage = proxy

    # В плагине:
    await self.storage.put("tokens", {"access": "..."})
    # Реально сохраняется как "oauth_provider:tokens"

    # Плагин НЕ может:
    await self.storage.put("oauth_other:tokens", ...)  # Forbidden
    await self.storage.get("oauth_other:tokens")        # Forbidden
"""

# Реализация изоляции теперь живёт в `core`, чтобы runtime мог
# включать безопасные дефолты без зависимости core -> modules.
from core.kernel.plugin_isolation import (
    DEFAULT_ALLOWED_SERVICES,
    EventBusProxy,
    NamespacedStorageProxy,
    ServiceProxy,
    ServiceRegistryProxy,
    StorageProxy,
)

__all__ = [
    "DEFAULT_ALLOWED_SERVICES",
    "EventBusProxy",
    "NamespacedStorageProxy",
    "ServiceProxy",
    "ServiceRegistryProxy",
    "StorageProxy",
]

