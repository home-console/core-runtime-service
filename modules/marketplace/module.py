"""
Marketplace module - plugin installation and lifecycle management.

Implements operations:
- marketplace.install
- marketplace.remove
- marketplace.update
- marketplace.enable
- marketplace.disable
- marketplace.list_installed
"""

from typing import Dict, Any, List, Optional
import inspect
from core.runtime.runtime_module import RuntimeModule
from core.http.models import EndpointAuthConfig, HttpEndpoint
from modules.marketplace.services import MarketplaceService
from modules.marketplace.admin_services import (
    admin_marketplace_disable,
    admin_marketplace_enable,
    admin_marketplace_install,
    admin_marketplace_install_from_registry,
    admin_marketplace_installed,
    admin_marketplace_remove,
    admin_marketplace_update,
    admin_marketplace_updates,
)
import logging
logger = logging.getLogger(__name__)


class MarketplaceModule(RuntimeModule):
    """
    Marketplace module for dynamic plugin installation.
    
    Provides:
    - marketplace.install - Install plugin from archive
    - marketplace.remove - Remove installed plugin
    - marketplace.update - Update to new version
    - marketplace.enable - Enable disabled plugin
    - marketplace.disable - Disable without removing
    - marketplace.list_installed - List installed plugins
    """
    
    def __init__(self, runtime: Any):
        """
        Initialize marketplace module.
        
        Args:
            runtime: Runtime instance
        """
        super().__init__(runtime)
        self._name = "marketplace"
        self._version = "1.0.0"
        self.service = MarketplaceService(runtime)
    
    @property
    def name(self) -> str:
        """Marketplace module name."""
        return self._name
    
    @property
    def version(self) -> str:
        """Marketplace module version."""
        return self._version
    
    async def register(self) -> None:
        """Register marketplace operations."""
        ops_mgr = self.context.operations or getattr(self.runtime, "operations", None)
        if ops_mgr is None:
            raise RuntimeError(
                "MarketplaceModule requires runtime.operations to register handlers. "
                "Check module wiring/bootstrap order."
            )
        # Register install operation
        ops_mgr.register_handler(
            "marketplace.install",
            self._wrap_handler(self.service.handle_install)
        )
        
        # Register remove operation
        ops_mgr.register_handler(
            "marketplace.remove",
            self._wrap_handler(self.service.handle_remove)
        )
        
        # Register update operation
        ops_mgr.register_handler(
            "marketplace.update",
            self._wrap_handler(self.service.handle_update)
        )
        
        # Register enable operation
        ops_mgr.register_handler(
            "marketplace.enable",
            self._wrap_handler(self.service.handle_enable)
        )
        
        # Register disable operation
        ops_mgr.register_handler(
            "marketplace.disable",
            self._wrap_handler(self.service.handle_disable)
        )
        
        # Register list_installed operation
        ops_mgr.register_handler(
            "marketplace.list_installed",
            self._wrap_handler(self.service.handle_list_installed)
        )
        
        # Register registry-based operations
        ops_mgr.register_handler(
            "marketplace.install_from_registry",
            self._wrap_handler(self.service.handle_install_from_registry)
        )
        
        ops_mgr.register_handler(
            "marketplace.search",
            self._wrap_handler(self.service.handle_search)
        )
        
        ops_mgr.register_handler(
            "marketplace.list_available",
            self._wrap_handler(self.service.handle_list_available)
        )
        
        ops_mgr.register_handler(
            "marketplace.check_updates",
            self._wrap_handler(self.service.handle_check_updates)
        )
        
        ops_mgr.register_handler(
            "marketplace.update_all",
            self._wrap_handler(self.service.handle_update_all)
        )

        # HTTP endpoints for admin marketplace operations (FastAPI via route_binding).
        http_registry = self.context.http
        services_reg = self.context.services
        services_reg_is_async = (
            inspect.iscoroutinefunction(getattr(services_reg, "register_with_acl", None))
            or inspect.iscoroutinefunction(getattr(services_reg, "register", None))
        )
        if http_registry is not None and services_reg_is_async:
            _admin_read = EndpointAuthConfig(required_scopes=["admin.read"])
            _admin_write = EndpointAuthConfig(required_scopes=["admin.write"])

            # Register services (called by HTTP layer via service_registry).
            await self.register_runtime_service("admin.v1.marketplace.install", admin_marketplace_install)
            await self.register_runtime_service(
                "admin.v1.marketplace.install_from_registry", admin_marketplace_install_from_registry
            )
            await self.register_runtime_service("admin.v1.marketplace.remove", admin_marketplace_remove)
            await self.register_runtime_service("admin.v1.marketplace.update", admin_marketplace_update)
            await self.register_runtime_service("admin.v1.marketplace.enable", admin_marketplace_enable)
            await self.register_runtime_service("admin.v1.marketplace.disable", admin_marketplace_disable)
            await self.register_runtime_service("admin.v1.marketplace.installed", admin_marketplace_installed)
            await self.register_runtime_service("admin.v1.marketplace.updates", admin_marketplace_updates)

            # Register HTTP endpoints → service mapping.
            http_registry.register(
                HttpEndpoint(
                    method="POST",
                    path="/admin/v1/marketplace/install",
                    service="admin.v1.marketplace.install",
                    description="Marketplace: install plugin from archive",
                    auth_config=_admin_write,
                )
            )
            http_registry.register(
                HttpEndpoint(
                    method="POST",
                    path="/admin/v1/marketplace/install-from-registry",
                    service="admin.v1.marketplace.install_from_registry",
                    description="Marketplace: install plugin from registry",
                    auth_config=_admin_write,
                )
            )
            http_registry.register(
                HttpEndpoint(
                    method="POST",
                    path="/admin/v1/marketplace/remove",
                    service="admin.v1.marketplace.remove",
                    description="Marketplace: remove plugin",
                    auth_config=_admin_write,
                )
            )
            http_registry.register(
                HttpEndpoint(
                    method="POST",
                    path="/admin/v1/marketplace/update",
                    service="admin.v1.marketplace.update",
                    description="Marketplace: update plugin",
                    auth_config=_admin_write,
                )
            )
            http_registry.register(
                HttpEndpoint(
                    method="POST",
                    path="/admin/v1/marketplace/enable/{plugin_name}",
                    service="admin.v1.marketplace.enable",
                    description="Marketplace: enable plugin",
                    auth_config=_admin_write,
                )
            )
            http_registry.register(
                HttpEndpoint(
                    method="POST",
                    path="/admin/v1/marketplace/disable/{plugin_name}",
                    service="admin.v1.marketplace.disable",
                    description="Marketplace: disable plugin",
                    auth_config=_admin_write,
                )
            )
            http_registry.register(
                HttpEndpoint(
                    method="GET",
                    path="/admin/v1/marketplace/installed",
                    service="admin.v1.marketplace.installed",
                    description="Marketplace: list installed plugins",
                    auth_config=_admin_read,
                )
            )
            http_registry.register(
                HttpEndpoint(
                    method="GET",
                    path="/admin/v1/marketplace/updates",
                    service="admin.v1.marketplace.updates",
                    description="Marketplace: check updates for installed plugins",
                    auth_config=_admin_read,
                )
            )
    
    async def start(self) -> None:
        """Start marketplace module."""
        # Register with capability registry
        if hasattr(self.runtime, 'capability_registry'):
            cap_reg = self.context.capabilities
            
            operations = [
                ("marketplace.install", "Install plugin from archive"),
                ("marketplace.remove", "Remove installed plugin"),
                ("marketplace.update", "Update plugin to new version"),
                ("marketplace.enable", "Enable disabled plugin"),
                ("marketplace.disable", "Disable plugin without removing"),
                ("marketplace.list_installed", "List installed marketplace plugins"),
                ("marketplace.install_from_registry", "Install from remote registry"),
                ("marketplace.search", "Search plugins in registry"),
                ("marketplace.list_available", "List available plugins"),
                ("marketplace.check_updates", "Check for available updates"),
                ("marketplace.update_all", "Update all plugins"),
            ]
            
            for op_name, description in operations:
                try:
                    maybe_coro = cap_reg.register_provider(self._name, op_name)
                    if inspect.isawaitable(maybe_coro):
                        await maybe_coro
                except Exception:
                    logger.debug(
                        "marketplace.start: register_provider skipped or failed op=%s",
                        op_name,
                        exc_info=True,
                    )
    
    async def stop(self) -> None:
        """Cleanup on shutdown."""
        # Unregister operations
        operations = [
            "marketplace.install",
            "marketplace.remove",
            "marketplace.update",
            "marketplace.enable",
            "marketplace.disable",
            "marketplace.list_installed",
            "marketplace.install_from_registry",
            "marketplace.search",
            "marketplace.list_available",
            "marketplace.check_updates",
            "marketplace.update_all",
        ]
        for op_name in operations:
            try:
                self.context.operations.unregister_handler(op_name)
            except Exception:
                logger.debug(
                    "marketplace.stop: unregister_handler skipped op=%s",
                    op_name,
                    exc_info=True,
                )
    
    async def on_start(self) -> None:
        """Alias for start() for backward compatibility."""
        await self.start()
    
    def list_capabilities(self) -> List[Dict[str, Any]]:
        """List marketplace capabilities."""
        return [
            {
                "name": "marketplace.install",
                "description": "Install plugin from archive (zip/tar.gz)"
            },
            {
                "name": "marketplace.remove",
                "description": "Remove installed plugin"
            },
            {
                "name": "marketplace.update",
                "description": "Update plugin to new version"
            },
            {
                "name": "marketplace.enable",
                "description": "Enable disabled plugin"
            },
            {
                "name": "marketplace.disable",
                "description": "Disable plugin without removing"
            },
            {
                "name": "marketplace.list_installed",
                "description": "List installed marketplace plugins"
            },
            {
                "name": "marketplace.install_from_registry",
                "description": "Install plugin from remote registry with version resolution"
            },
            {
                "name": "marketplace.search",
                "description": "Search plugins in registry by name or description"
            },
            {
                "name": "marketplace.list_available",
                "description": "List all available plugins and versions"
            },
            {
                "name": "marketplace.check_updates",
                "description": "Check for available updates to installed plugins"
            },
            {
                "name": "marketplace.update_all",
                "description": "Update all plugins to latest versions"
            },
        ]
    
    def _wrap_handler(self, handler):
        """Wrap MarketplaceService handler for OperationManager."""
        async def wrapped(runtime, operation):
            result = await handler(operation)
            return {
                "status": result.get("status"),
                "data": result.get("data"),
                "error": result.get("error")
            }
        return wrapped
    
    def list_installed_plugins(self) -> Dict[str, Any]:
        """Get installed plugins from storage."""
        storage = getattr(self.runtime, "storage", None)
        if hasattr(storage, "get_sync"):
            return (storage.get_sync("marketplace.installed") or {})
        return {}
    
    def get_manifest(self, plugin_name: str) -> Optional[Dict[str, Any]]:
        """
        Get plugin manifest from storage.
        
        Args:
            plugin_name: Name of plugin
            
        Returns:
            Plugin manifest or None if not found
        """
        installed = self.list_installed_plugins()
        return installed.get(plugin_name)
    
    async def health_check(self) -> Dict[str, Any]:
        """Health check for marketplace module."""
        installed = self.list_installed_plugins()
        return {
            "status": "healthy",
            "installed_plugins_count": len(installed),
            "operations_available": [
                "marketplace.install",
                "marketplace.remove",
                "marketplace.update",
                "marketplace.enable",
                "marketplace.disable",
                "marketplace.list_installed",
                "marketplace.install_from_registry",
                "marketplace.search",
                "marketplace.list_available",
                "marketplace.check_updates",
                "marketplace.update_all",
            ]
        }
