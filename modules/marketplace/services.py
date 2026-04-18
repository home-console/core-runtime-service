import logging
"""
Marketplace service - operation handlers.

Exposes operations:
- marketplace.install
- marketplace.remove
- marketplace.update
- marketplace.enable
- marketplace.disable
- marketplace.list_installed
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from core.operations.models import Operation
from modules.marketplace.installer import InstallerError, MarketplaceInstaller
from modules.marketplace.registry_client import RegistryClient
from modules.marketplace.transaction import UpdateTransactionManager
from modules.marketplace.update_validator import PluginUpdateValidator
logger = logging.getLogger(__name__)


class MarketplaceServiceError(Exception):
    """Marketplace service error."""

    pass


class MarketplaceService:
    """
    Service for marketplace operations.

    Handles plugin installation, removal, updates, and tracking
    via capability routing.
    """

    def __init__(self, runtime: Any):
        """
        Initialize service.

        Args:
            runtime: Runtime instance with storage, plugin_manager
        """
        self.runtime = runtime
        self.storage = runtime.storage
        self.plugin_manager = runtime.plugin_manager

        # Initialize installer and transaction manager for atomic updates
        plugins_dir_value = None
        cfg = getattr(runtime, "config", None)
        if cfg is not None:
            # Real runtime uses Config object; tests often use dict.
            plugins_dir_value = getattr(cfg, "plugins_dir", None)
            if plugins_dir_value is None and isinstance(cfg, dict):
                plugins_dir_value = cfg.get("plugins_dir")
        plugins_dir = Path(str(plugins_dir_value or "plugins"))
        self.installer = MarketplaceInstaller(plugins_dir)
        self.transaction_mgr = UpdateTransactionManager(plugins_dir, runtime)

    async def handle_install(self, operation: Operation) -> Dict[str, Any]:
        """
        Install plugin from archive.

        Args:
            operation.params: {
                "archive_path": str,
                "sha256": Optional[str]
            }

        Returns:
            Dict with status, data, and error
        """
        params = operation.params or {}
        archive_path = params.get("archive_path")
        sha256 = params.get("sha256")

        if not archive_path:
            return {"status": "failure", "error": "archive_path required"}

        try:
            result = await self.installer.install_from_file(
                archive_path, sha256=sha256, runtime=self.runtime
            )

            # Store installation info
            self._store_installed_plugin(result)

            # Log to audit trail
            plugin_name = result.get("name")
            plugin_version = result.get("version")
            audit_entry = {
                "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                "action": "install",
                "plugin_name": plugin_name,
                "version": plugin_version,
                "status": "success",
                "reason": None,
                "source": "archive",
                "archive_hash": result.get("hash"),
            }
            self._add_audit_log(audit_entry)

            return {"status": "success", "data": result}

        except InstallerError as e:
            # Log failure
            audit_entry = {
                "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                "action": "install",
                "status": "failure",
                "reason": str(e),
                "source": "archive",
            }
            self._add_audit_log(audit_entry)

            return {"status": "failure", "error": str(e)}

    async def handle_remove(self, operation: Operation) -> Dict[str, Any]:
        """
        Remove installed plugin.

        Args:
            operation.params: {
                "plugin_name": str
            }

        Returns:
            Dict with status, data, and error
        """
        params = operation.params or {}
        plugin_name = params.get("plugin_name")

        if not plugin_name:
            return {"status": "failure", "error": "plugin_name required"}

        try:
            # Get plugin info before uninstall
            installed = self._get_installed_plugins()
            if plugin_name not in installed:
                return {
                    "status": "failure",
                    "error": f"Plugin not installed: {plugin_name}",
                }

            plugin_info = installed[plugin_name]

            # Validate that plugin can be removed (no dependencies on it)
            try:
                policy = getattr(getattr(self.runtime, "plugins", None), "lifecycle_policy", None)
                if policy is not None:
                    ok, errors = policy.can_remove_plugin(plugin_name)
                    if not ok and errors:
                        return {
                            "status": "failure",
                            "error": f"Cannot remove {plugin_name}: " + "\n".join(errors),
                        }
            except (TypeError, AttributeError):
                # В тестах с mock runtime plugins/lifecycle_policy может отсутствовать
                pass

            # Uninstall
            result = await self.installer.uninstall(plugin_name, runtime=self.runtime)

            # Clear from storage
            self._remove_installed_plugin(plugin_name)

            return {"status": "success", "data": result}

        except InstallerError as e:
            return {"status": "failure", "error": str(e)}

    async def handle_update(self, operation: Operation) -> Dict[str, Any]:
        """
        Update plugin to new version.

        Args:
            operation.params: {
                "plugin_name": str,
                "archive_path": str,
                "sha256": Optional[str]
            }

        Returns:
            Dict with status, data, and error
        """
        params = operation.params or {}
        plugin_name = params.get("plugin_name")
        archive_path = params.get("archive_path")

        if not plugin_name or not archive_path:
            return {
                "status": "failure",
                "error": "plugin_name and archive_path required",
            }

        try:
            # Check plugin exists
            installed = self._get_installed_plugins()
            if plugin_name not in installed:
                return {
                    "status": "failure",
                    "error": f"Plugin not installed: {plugin_name}",
                }

            old_info = installed[plugin_name]
            old_version = old_info.get("version")

            # Remove old version
            await self.installer.uninstall(plugin_name, runtime=self.runtime)
            self._remove_installed_plugin(plugin_name)

            # Install new version
            result = await self.installer.install_from_file(
                archive_path, sha256=params.get("sha256"), runtime=self.runtime
            )

            self._store_installed_plugin(result)
            new_version = result["version"]

            # Log to audit trail
            audit_entry = {
                "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                "action": "update",
                "plugin_name": plugin_name,
                "old_version": old_version,
                "new_version": new_version,
                "status": "success",
                "reason": None,
                "archive_hash": result.get("hash"),
            }
            self._add_audit_log(audit_entry)

            return {
                "status": "success",
                "data": {
                    "plugin_name": plugin_name,
                    "old_version": old_version,
                    "new_version": new_version,
                    "updated_at": datetime.now(timezone.utc).isoformat() + "Z",
                },
            }

        except InstallerError as e:
            # Log failure
            audit_entry = {
                "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                "action": "update",
                "plugin_name": plugin_name,
                "status": "failure",
                "reason": str(e),
            }
            self._add_audit_log(audit_entry)

            return {"status": "failure", "error": str(e)}

    async def handle_enable(self, operation: Operation) -> Dict[str, Any]:
        """
        Enable an installed plugin.

        Args:
            operation.params: {
                "plugin_name": str
            }

        Returns:
            Dict with status, data, and error
        """
        params = operation.params or {}
        plugin_name = params.get("plugin_name")

        if not plugin_name:
            return {"status": "failure", "error": "plugin_name required"}

        try:
            # Get plugin info
            installed = self._get_installed_plugins()
            if plugin_name not in installed:
                return {
                    "status": "failure",
                    "error": f"Plugin not installed: {plugin_name}",
                }

            # Start plugin if manager available
            if hasattr(self.plugin_manager, "start_plugin"):
                await self.plugin_manager.start_plugin(plugin_name)

            # Mark as enabled in storage
            plugin_info = installed[plugin_name]
            plugin_info["enabled"] = True
            plugin_info["enabled_at"] = datetime.now(timezone.utc).isoformat()
            self._store_installed_plugin(plugin_info)

            return {
                "status": "success",
                "data": {"plugin_name": plugin_name, "enabled": True},
            }

        except Exception as e:
            logger.warning("handle_enable failed for plugin %s: %s", params.get("plugin_name"), e, exc_info=True)
            return {"status": "failure", "error": str(e)}

    async def handle_disable(self, operation: Operation) -> Dict[str, Any]:
        """
        Disable an installed plugin.

        Args:
            operation.params: {
                "plugin_name": str
            }

        Returns:
            Dict with status, data, and error
        """
        params = operation.params or {}
        plugin_name = params.get("plugin_name")

        if not plugin_name:
            return {"status": "failure", "error": "plugin_name required"}

        try:
            # Get plugin info
            installed = self._get_installed_plugins()
            if plugin_name not in installed:
                return {
                    "status": "failure",
                    "error": f"Plugin not installed: {plugin_name}",
                }

            # Validate that plugin can be disabled (no dependencies on it)
            if self.runtime is not None and hasattr(self.runtime, "dependency_resolver"):
                try:
                    errors = self.runtime.dependency_resolver.validate_plugin_disable(
                        plugin_name
                    )
                    if errors:
                        return {
                            "status": "failure",
                            "error": f"Cannot disable {plugin_name}: "
                            + "\n".join(errors),
                        }
                except (TypeError, AttributeError):
                    # В тестах с mock runtime dependency_resolver может отсутствовать
                    pass

            # Stop plugin if manager available
            if hasattr(self.plugin_manager, "stop_plugin"):
                await self.plugin_manager.stop_plugin(plugin_name)

            # Mark as disabled in storage
            plugin_info = installed[plugin_name]
            plugin_info["enabled"] = False
            plugin_info["disabled_at"] = datetime.now(timezone.utc).isoformat()
            self._store_installed_plugin(plugin_info)

            return {
                "status": "success",
                "data": {"plugin_name": plugin_name, "enabled": False},
            }

        except Exception as e:
            logger.warning("handle_disable failed for plugin %s: %s", plugin_name, e, exc_info=True)
            return {"status": "failure", "error": str(e)}

    async def handle_list_installed(self, operation: Operation) -> Dict[str, Any]:
        """
        List installed marketplace plugins.

        Returns all installed plugins from storage.

        Returns:
            Dict with status, data, and error
        """
        try:
            installed = self._get_installed_plugins()
            return {
                "status": "success",
                "data": {"installed_plugins": installed, "count": len(installed)},
            }
        except Exception as e:
            logger.warning("handle_list_installed failed: %s", e, exc_info=True)
            return {"status": "failure", "error": str(e)}

    def _store_installed_plugin(self, plugin_info: Dict[str, Any]) -> None:
        """Store plugin info in storage.installed namespace."""
        installed = self._get_installed_plugins()
        plugin_name = plugin_info["name"]

        # Normalize storage format
        installed[plugin_name] = {
            "name": plugin_info["name"],
            "version": plugin_info["version"],
            "path": plugin_info["path"],
            "hash": plugin_info["hash"],
            "class_path": plugin_info["class_path"],
            "installed_at": plugin_info["installed_at"],
            "enabled": plugin_info.get("enabled", True),
            "capabilities_provided": plugin_info.get("capabilities_provided", []),
            "capabilities_required": plugin_info.get("capabilities_required", []),
        }

        self.storage.set("marketplace.installed", installed)

    def _remove_installed_plugin(self, plugin_name: str) -> None:
        """Remove plugin from storage.installed namespace."""
        installed = self._get_installed_plugins()
        if plugin_name in installed:
            del installed[plugin_name]
            self.storage.set("marketplace.installed", installed)

    def _get_installed_plugins(self) -> Dict[str, Dict[str, Any]]:
        """Get all installed plugins from storage."""
        return self.storage.get("marketplace.installed") or {}

    # ========== Registry-based operations ==========

    async def handle_install_from_registry(
        self, operation: Operation
    ) -> Dict[str, Any]:
        """
        Install plugin from remote registry.

        Args:
            operation.params: {
                "plugin_name": str,
                "version_constraint": Optional[str],  # e.g., "^1.2.0", None = latest
                "channel": str,  # "stable", "beta", default = "stable"
                "registry_url": str,  # Registry index URL (HTTPS)
                "force_update": bool,  # Allow downgrade
            }

        Returns:
            Dict with status, data, error
        """
        params = operation.params or {}
        plugin_name = params.get("plugin_name")
        version_constraint = params.get("version_constraint")
        channel = params.get("channel", "stable")
        cfg = getattr(self.runtime, "config", None)
        default_registry_url = None
        if cfg is not None:
            default_registry_url = getattr(cfg, "marketplace_registry_url", None)
            if default_registry_url is None and isinstance(cfg, dict):
                default_registry_url = cfg.get("marketplace_registry_url")

        registry_url = params.get("registry_url") or (str(default_registry_url or "").strip() or None)
        force_update = params.get("force_update", False)

        if not plugin_name:
            return {
                "status": "failure",
                "error": "plugin_name required",
            }
        if not registry_url:
            return {"status": "failure", "error": "registry_url not configured"}

        try:
            # Resolve version from registry
            client = RegistryClient(registry_url)
            release = await client.resolve(
                plugin_name, version_constraint=version_constraint, channel=channel
            )

            # Validate SHA256 after download
            result = await self.installer.install_from_url(
                release.url,
                sha256=release.sha256,
                signature=release.signature,
                public_key=release.public_key,
                runtime=self.runtime,
                force_update=force_update,
            )

            # Store with registry metadata
            self._store_installed_plugin(result)
            self._store_registry_metadata(
                plugin_name, release.version, registry_url, channel
            )

            # Log to audit trail
            audit_entry = {
                "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                "action": "install_from_registry",
                "plugin_name": plugin_name,
                "version": release.version,
                "version_constraint": version_constraint,
                "channel": channel,
                "registry": registry_url,
                "status": "success",
                "reason": None,
                "archive_hash": result.get("hash"),
                "registry_downgrade_protection": "enabled",
            }
            self._add_audit_log(audit_entry)

            return {
                "status": "success",
                "data": {**result, "registry": registry_url, "channel": channel},
            }

        except Exception as e:
            # Log failure
            audit_entry = {
                "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                "action": "install_from_registry",
                "plugin_name": plugin_name,
                "version_constraint": version_constraint,
                "channel": channel,
                "registry": registry_url,
                "status": "failure",
                "reason": str(e),
            }
            self._add_audit_log(audit_entry)

            logger.warning("handle_install_from_registry failed for plugin %s: %s", plugin_name, e, exc_info=True)
            return {"status": "failure", "error": str(e)}

    async def handle_search(self, operation: Operation) -> Dict[str, Any]:
        """
        Search registry for plugins.

        Args:
            operation.params: {
                "query": str,  # Name or description search
                "registry_url": str,
            }

        Returns:
            Dict with matching plugins
        """
        params = operation.params or {}
        query = params.get("query", "")
        registry_url = params.get("registry_url")

        if not registry_url:
            return {"status": "failure", "error": "registry_url required"}

        try:
            client = RegistryClient(registry_url)
            results = await client.search(query)

            return {"status": "success", "data": {"query": query, "results": results}}

        except Exception as e:
            logger.warning("handle_search failed for query %r: %s", query, e, exc_info=True)
            return {"status": "failure", "error": str(e)}

    async def handle_list_available(self, operation: Operation) -> Dict[str, Any]:
        """
        List all available plugins in registry.

        Args:
            operation.params: {
                "registry_url": str,
            }

        Returns:
            Dict with plugin names and versions
        """
        params = operation.params or {}
        registry_url = params.get("registry_url")

        if not registry_url:
            return {"status": "failure", "error": "registry_url required"}

        try:
            client = RegistryClient(registry_url)
            available = await client.list_available()

            return {
                "status": "success",
                "data": {"count": len(available), "plugins": available},
            }

        except Exception as e:
            logger.warning("handle_list_available failed for registry %s: %s", registry_url, e, exc_info=True)
            return {"status": "failure", "error": str(e)}

    async def handle_check_updates(self, operation: Operation) -> Dict[str, Any]:
        """
        Check for available updates.

        Args:
            operation.params: {
                "registry_url": str,
                "channel": str,  # "stable", "beta"
            }

        Returns:
            Dict with available updates
        """
        params = operation.params or {}
        registry_url = params.get("registry_url")
        channel = params.get("channel", "stable")

        if not registry_url:
            return {"status": "failure", "error": "registry_url required"}

        try:
            client = RegistryClient(registry_url)
            validator = PluginUpdateValidator(self.runtime)

            installed = self._get_installed_plugins()
            updates = {}

            # Check each installed plugin
            for plugin_name, plugin_info in installed.items():
                try:
                    # Get available versions
                    available = await client.list_available()
                    versions = available.get(plugin_name, [])

                    if not versions:
                        continue

                    # Check for update
                    new_version = await validator.check_for_updates(
                        plugin_info["version"], versions, channel=channel
                    )

                    if new_version:
                        updates[plugin_name] = {
                            "current": plugin_info["version"],
                            "available": new_version,
                        }

                except Exception:
                    # Log but don't fail
                    logger.warning("handle_check_updates: failed to check updates for plugin %s: %s", plugin_name, exc_info=True)

            return {
                "status": "success",
                "data": {"updates_available": len(updates), "updates": updates},
            }

        except Exception as e:
            logger.warning("handle_check_updates failed: %s", e, exc_info=True)
            return {"status": "failure", "error": str(e)}

    async def handle_update_all(self, operation: Operation) -> Dict[str, Any]:
        """
        Update all plugins to latest versions.

        Args:
            operation.params: {
                "registry_url": str,
                "channel": str,
                "force": bool,
            }

        Returns:
            Dict with update results
        """
        params = operation.params or {}
        registry_url = params.get("registry_url")
        channel = params.get("channel", "stable")
        force = params.get("force", False)

        if not registry_url:
            return {"status": "failure", "error": "registry_url required"}

        try:
            client = RegistryClient(registry_url)
            validator = PluginUpdateValidator(self.runtime)

            installed = self._get_installed_plugins()
            results = {"updated": [], "skipped": [], "errors": []}

            # Update each plugin
            for plugin_name, plugin_info in installed.items():
                try:
                    release = await client.resolve(plugin_name, channel=channel)

                    # Validate update
                    check = validator.validate_plugin_update(
                        plugin_info, {"version": release.version}, force=force
                    )

                    if not check.can_update:
                        results["skipped"].append(
                            {
                                "plugin": plugin_name,
                                "reason": check.reason,
                                "issues": check.blocking_issues,
                            }
                        )
                        continue

                    # Install update
                    result = await self.installer.install_from_url(
                        release.url,
                        sha256=release.sha256,
                        signature=release.signature,
                        public_key=release.public_key,
                        runtime=self.runtime,
                        force_update=force,
                    )

                    results["updated"].append(
                        {"plugin": plugin_name, "version": release.version}
                    )

                    self._store_installed_plugin(result)

                except Exception as e:
                    logger.warning("handle_update_all: failed to update plugin %s: %s", plugin_name, e, exc_info=True)
                    results["errors"].append({"plugin": plugin_name, "error": str(e)})

            return {
                "status": "success" if not results["errors"] else "partial_failure",
                "data": results,
            }

        except Exception as e:
            logger.warning("handle_update_all failed: %s", e, exc_info=True)
            return {"status": "failure", "error": str(e)}

    def _add_audit_log(self, audit_entry: Dict[str, Any]) -> None:
        """Add entry to marketplace audit log."""
        try:
            audit_log = self.storage.get("marketplace.audit", {})

            # Generate log ID from timestamp
            import uuid

            log_id = str(uuid.uuid4())

            audit_log[log_id] = audit_entry
            self.storage.set("marketplace.audit", audit_log)
        except Exception as e:
            # Don't fail the main operation if audit logging fails
            import logging

            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to write audit log: {e}")

    def _store_registry_metadata(
        self, plugin_name: str, version: str, registry_url: str, channel: str
    ) -> None:
        """Store registry metadata for installed plugin."""
        registry_meta = self.storage.get("marketplace.registry_meta") or {}

        if plugin_name not in registry_meta:
            registry_meta[plugin_name] = {}

        registry_meta[plugin_name].update(
            {
                "version": version,
                "registry_url": registry_url,
                "channel": channel,
                "updated_at": datetime.now(timezone.utc).isoformat() + "Z",
            }
        )

        self.storage.set("marketplace.registry_meta", registry_meta)
