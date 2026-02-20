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
from core.runtime_module import RuntimeModule
from modules.marketplace.services import MarketplaceService


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
        # Register install operation
        self.runtime.operations.register_handler(
            "marketplace.install",
            self._wrap_handler(self.service.handle_install)
        )
        
        # Register remove operation
        self.runtime.operations.register_handler(
            "marketplace.remove",
            self._wrap_handler(self.service.handle_remove)
        )
        
        # Register update operation
        self.runtime.operations.register_handler(
            "marketplace.update",
            self._wrap_handler(self.service.handle_update)
        )
        
        # Register enable operation
        self.runtime.operations.register_handler(
            "marketplace.enable",
            self._wrap_handler(self.service.handle_enable)
        )
        
        # Register disable operation
        self.runtime.operations.register_handler(
            "marketplace.disable",
            self._wrap_handler(self.service.handle_disable)
        )
        
        # Register list_installed operation
        self.runtime.operations.register_handler(
            "marketplace.list_installed",
            self._wrap_handler(self.service.handle_list_installed)
        )
        
        # Step 12: Register registry-based operations
        self.runtime.operations.register_handler(
            "marketplace.install_from_registry",
            self._wrap_handler(self.service.handle_install_from_registry)
        )
        
        self.runtime.operations.register_handler(
            "marketplace.search",
            self._wrap_handler(self.service.handle_search)
        )
        
        self.runtime.operations.register_handler(
            "marketplace.list_available",
            self._wrap_handler(self.service.handle_list_available)
        )
        
        self.runtime.operations.register_handler(
            "marketplace.check_updates",
            self._wrap_handler(self.service.handle_check_updates)
        )
        
        self.runtime.operations.register_handler(
            "marketplace.update_all",
            self._wrap_handler(self.service.handle_update_all)
        )
    
    async def start(self) -> None:
        """Start marketplace module."""
        # Register with capability registry
        if hasattr(self.runtime, 'capability_registry'):
            cap_reg = self.runtime.capability_registry
            
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
                    cap_reg.register_provider(self._name, op_name)
                except Exception:
                    pass  # May already be registered
    
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
                self.runtime.operations.unregister_handler(op_name)
            except Exception:
                pass  # Already unregistered
    
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
        # REFACTORING: Синхронный метод, но storage асинхронный
        # Для обратной совместимости используем runtime.storage напрямую
        # TODO: Переделать на async или добавить синхронный wrapper
        storage = self.context.storage if hasattr(self, "context") and self.context else self.runtime.storage
        # Внимание: это синхронный вызов, но storage.get асинхронный
        # Это legacy код, который нужно будет переделать
        if hasattr(storage, "get_sync"):
            return (storage.get_sync("marketplace.installed") or {})
        # Fallback на runtime.storage для синхронного доступа (legacy)
        return (self.runtime.storage.get("marketplace.installed") or {})
    
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
