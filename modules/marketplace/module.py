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
import asyncio
import logging
from datetime import datetime, timezone
from core.runtime.runtime_module import RuntimeModule
from core.http.models import EndpointAuthConfig, HttpEndpoint
from modules.api.schemas import (
    ApiResponse,
    BuildGitCatalogRequest,
    GitCatalogEntryDto,
    GitSourcesDto,
    InstallFromArchiveRequest,
    InstallFromGitRequest,
    InstallFromRegistryRequest,
    UpdateFromRegistryRequest,
    InstalledPluginDto,
    MarketplaceResultDto,
    RemovePluginRequest,
    SetGitSourcesRequest,
    UpdatePluginRequest,
)
from modules.marketplace.services import MarketplaceService
from modules.marketplace.registry_client import RegistryClient
from modules.marketplace.admin_services import (
    admin_marketplace_disable,
    admin_marketplace_enable,
    admin_marketplace_install,
    admin_marketplace_install_upload,
    admin_marketplace_install_from_git,
    admin_marketplace_install_from_registry,
    admin_marketplace_update_from_registry,
    admin_marketplace_installed,
    admin_marketplace_git_sources_get,
    admin_marketplace_git_sources_set,
    admin_marketplace_git_catalog,
    admin_marketplace_remove,
    admin_marketplace_update,
    admin_marketplace_updates,
)
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
        self._registry_probe_ok: Optional[bool] = None
        self._registry_probe_error: Optional[str] = None
        self._registry_probe_checked_at: Optional[str] = None

    _MARKETPLACE_HANDLER_EXTRA_KEYS = frozenset({"error_stage", "user_message"})
    
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
        
        # Health check: verify registry is accessible (if configured)
        await self._probe_registry()
        
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
            "marketplace.update_from_registry",
            self._wrap_handler(self.service.handle_update_from_registry)
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
                "admin.v1.marketplace.install_upload", admin_marketplace_install_upload
            )
            await self.register_runtime_service(
                "admin.v1.marketplace.install_from_git", admin_marketplace_install_from_git
            )
            await self.register_runtime_service(
                "admin.v1.marketplace.install_from_registry", admin_marketplace_install_from_registry
            )
            await self.register_runtime_service(
                "admin.v1.marketplace.update_from_registry", admin_marketplace_update_from_registry
            )
            await self.register_runtime_service(
                "admin.v1.marketplace.git_sources.get", admin_marketplace_git_sources_get
            )
            await self.register_runtime_service(
                "admin.v1.marketplace.git_sources.set", admin_marketplace_git_sources_set
            )
            await self.register_runtime_service(
                "admin.v1.marketplace.git_catalog", admin_marketplace_git_catalog
            )
            await self.register_runtime_service("admin.v1.marketplace.remove", admin_marketplace_remove)
            await self.register_runtime_service("admin.v1.marketplace.update", admin_marketplace_update)
            await self.register_runtime_service("admin.v1.marketplace.enable", admin_marketplace_enable)
            await self.register_runtime_service("admin.v1.marketplace.disable", admin_marketplace_disable)
            await self.register_runtime_service("admin.v1.marketplace.installed", admin_marketplace_installed)
            await self.register_runtime_service("admin.v1.marketplace.updates", admin_marketplace_updates)

            # Register HTTP endpoints → service mapping.
            http_registry.register(HttpEndpoint(
                method="POST",
                path="/api/v1/admin/marketplace/install",
                service="admin.v1.marketplace.install",
                description="Marketplace: install plugin from archive",
                auth_config=_admin_write,
                tags=["Marketplace"],
                response_model=MarketplaceResultDto,
                request_model=InstallFromArchiveRequest,
            ))
            http_registry.register(HttpEndpoint(
                method="POST",
                path="/api/v1/admin/marketplace/install-upload",
                service="admin.v1.marketplace.install_upload",
                description="Marketplace: install plugin from uploaded archive (multipart: file)",
                auth_config=_admin_write,
                tags=["Marketplace"],
                response_model=MarketplaceResultDto,
            ))
            http_registry.register(HttpEndpoint(
                method="POST",
                path="/api/v1/admin/marketplace/install-from-registry",
                service="admin.v1.marketplace.install_from_registry",
                description="Marketplace: install plugin from registry",
                auth_config=_admin_write,
                tags=["Marketplace"],
                response_model=MarketplaceResultDto,
                request_model=InstallFromRegistryRequest,
            ))
            http_registry.register(HttpEndpoint(
                method="POST",
                path="/api/v1/admin/marketplace/update-from-registry",
                service="admin.v1.marketplace.update_from_registry",
                description="Marketplace: update installed plugin from registry (same version OK)",
                auth_config=_admin_write,
                tags=["Marketplace"],
                response_model=MarketplaceResultDto,
                request_model=UpdateFromRegistryRequest,
            ))
            http_registry.register(HttpEndpoint(
                method="POST",
                path="/api/v1/admin/marketplace/install-from-git",
                service="admin.v1.marketplace.install_from_git",
                description="Marketplace: install plugin from git repo (tarball HTTPS)",
                auth_config=_admin_write,
                tags=["Marketplace"],
                response_model=MarketplaceResultDto,
                request_model=InstallFromGitRequest,
            ))
            http_registry.register(HttpEndpoint(
                method="GET",
                path="/api/v1/admin/marketplace/git-sources",
                service="admin.v1.marketplace.git_sources.get",
                description="Marketplace: get git sources list (persisted)",
                auth_config=_admin_read,
                tags=["Marketplace"],
                response_model=ApiResponse[GitSourcesDto],
            ))
            http_registry.register(HttpEndpoint(
                method="POST",
                path="/api/v1/admin/marketplace/git-sources",
                service="admin.v1.marketplace.git_sources.set",
                description="Marketplace: set git sources list (persisted)",
                auth_config=_admin_write,
                tags=["Marketplace"],
                response_model=ApiResponse[GitSourcesDto],
                request_model=SetGitSourcesRequest,
            ))
            http_registry.register(HttpEndpoint(
                method="POST",
                path="/api/v1/admin/marketplace/git-catalog",
                service="admin.v1.marketplace.git_catalog",
                description="Marketplace: build catalog from git sources (no install)",
                auth_config=_admin_read,
                tags=["Marketplace"],
                response_model=ApiResponse[List[GitCatalogEntryDto]],
                request_model=BuildGitCatalogRequest,
            ))
            http_registry.register(HttpEndpoint(
                method="POST",
                path="/api/v1/admin/marketplace/remove",
                service="admin.v1.marketplace.remove",
                description="Marketplace: remove plugin",
                auth_config=_admin_write,
                tags=["Marketplace"],
                response_model=MarketplaceResultDto,
                request_model=RemovePluginRequest,
            ))
            http_registry.register(HttpEndpoint(
                method="POST",
                path="/api/v1/admin/marketplace/update",
                service="admin.v1.marketplace.update",
                description="Marketplace: update plugin",
                auth_config=_admin_write,
                tags=["Marketplace"],
                response_model=MarketplaceResultDto,
                request_model=UpdatePluginRequest,
            ))
            http_registry.register(HttpEndpoint(
                method="POST",
                path="/api/v1/admin/marketplace/enable/{plugin_name}",
                service="admin.v1.marketplace.enable",
                description="Marketplace: enable plugin",
                auth_config=_admin_write,
                tags=["Marketplace"],
                response_model=MarketplaceResultDto,
            ))
            http_registry.register(HttpEndpoint(
                method="POST",
                path="/api/v1/admin/marketplace/disable/{plugin_name}",
                service="admin.v1.marketplace.disable",
                description="Marketplace: disable plugin",
                auth_config=_admin_write,
                tags=["Marketplace"],
                response_model=MarketplaceResultDto,
            ))
            http_registry.register(HttpEndpoint(
                method="GET",
                path="/api/v1/admin/marketplace/installed",
                service="admin.v1.marketplace.installed",
                description="Marketplace: list installed plugins",
                auth_config=_admin_read,
                tags=["Marketplace"],
                response_model=ApiResponse[List[InstalledPluginDto]],
            ))
            http_registry.register(HttpEndpoint(
                method="GET",
                path="/api/v1/admin/marketplace/updates",
                service="admin.v1.marketplace.updates",
                description="Marketplace: check updates for installed plugins",
                auth_config=_admin_read,
                tags=["Marketplace"],
                response_model=ApiResponse[List[InstalledPluginDto]],
            ))
    
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
                ("marketplace.update_from_registry", "Update installed plugin from registry"),
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
            "marketplace.update_from_registry",
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
                "name": "marketplace.update_from_registry",
                "description": "Update installed plugin from registry (reinstall same version allowed)"
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
    
    async def _probe_registry(self) -> None:
        """
        Health check: verify registry is accessible.
        
        Called during module registration. If registry is configured but unreachable,
        logs a warning but does not fail startup (marketplace operations may work
        if registry becomes available later).
        """
        cfg = getattr(self.runtime, "config", None)
        if cfg is None:
            self._registry_probe_ok = None
            self._registry_probe_error = "runtime config unavailable"
            self._registry_probe_checked_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            logger.debug("No config available for registry probe")
            return
        
        registry_url = getattr(cfg, "marketplace_registry_url", "")
        if not registry_url or not registry_url.strip():
            self._registry_probe_ok = None
            self._registry_probe_error = "marketplace registry url not configured"
            self._registry_probe_checked_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            logger.info("marketplace: no registry configured (MARKETPLACE_REGISTRY_URL not set)")
            return
        
        try:
            logger.info(f"marketplace: probing registry at {registry_url}...")
            client = RegistryClient(registry_url)
            
            # Attempt to fetch index with short timeout
            # Use asyncio.wait_for with 5 second timeout
            try:
                await asyncio.wait_for(client.fetch_index(), timeout=5.0)
                self._registry_probe_ok = True
                self._registry_probe_error = None
                self._registry_probe_checked_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                logger.info("marketplace: registry health check passed")
            except asyncio.TimeoutError:
                self._registry_probe_ok = False
                self._registry_probe_error = f"registry health check timed out after 5s: {registry_url}"
                self._registry_probe_checked_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                logger.warning(
                    f"marketplace: registry health check timed out after 5s: {registry_url}"
                )
            except Exception as e:
                self._registry_probe_ok = False
                self._registry_probe_error = str(e)
                self._registry_probe_checked_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                logger.warning(
                    f"marketplace: registry health check failed: {registry_url} — {e}"
                )
        except Exception as e:
            self._registry_probe_ok = False
            self._registry_probe_error = str(e)
            self._registry_probe_checked_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            logger.warning(f"marketplace: registry probe exception: {e}")
    
    def _wrap_handler(self, handler):
        """Wrap MarketplaceService handler for OperationManager."""
        extras = self._MARKETPLACE_HANDLER_EXTRA_KEYS

        async def wrapped(runtime, operation):
            if isinstance(runtime, dict) and isinstance(operation, dict):
                from types import SimpleNamespace
                params = SimpleNamespace(params=runtime)
            else:
                params = operation
            result = await handler(params)
            out = {
                "status": result.get("status"),
                "data": result.get("data"),
                "error": result.get("error"),
            }
            for key in extras:
                if key in result:
                    out[key] = result[key]
            return out

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
            "registry_probe": {
                "ok": self._registry_probe_ok,
                "error": self._registry_probe_error,
                "checked_at": self._registry_probe_checked_at,
            },
            "operations_available": [
                "marketplace.install",
                "marketplace.remove",
                "marketplace.update",
                "marketplace.enable",
                "marketplace.disable",
                "marketplace.list_installed",
                "marketplace.install_from_registry",
                "marketplace.update_from_registry",
                "marketplace.search",
                "marketplace.list_available",
                "marketplace.check_updates",
                "marketplace.update_all",
            ]
        }
