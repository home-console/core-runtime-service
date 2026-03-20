"""
Plugin Update Validator — check update safety and validity.

Step 12: Validates:
- Version constraints (no downgrade without force)
- Dependency compatibility
- Capability availability after update
- Trust level changes
"""

from typing import Any, Dict, List, Optional
from dataclasses import dataclass
import logging

from modules.marketplace.semver import Version

logger = logging.getLogger(__name__)


class UpdateValidationError(Exception):
    """Plugin update validation failed."""
    pass


@dataclass
class UpdateCheck:
    """Result of update check."""
    can_update: bool
    reason: str = ""
    blocking_issues: Optional[List[str]] = None
    warnings: Optional[List[str]] = None
    
    def __init__(self, can_update: bool, **kwargs):
        self.can_update = can_update
        self.reason = kwargs.get("reason", "")
        self.blocking_issues = kwargs.get("blocking_issues", [])
        self.warnings = kwargs.get("warnings", [])


class PluginUpdateValidator:
    """Validate plugin updates for safety and compatibility."""
    
    def __init__(self, runtime=None):
        """
        Initialize validator.
        
        Args:
            runtime: Runtime instance (for dependency resolution)
        """
        self._runtime = runtime
    
    def validate_plugin_update(self,
                              old_plugin: Dict[str, Any],
                              new_plugin: Dict[str, Any],
                              force: bool = False) -> UpdateCheck:
        """
        Validate plugin update from old to new version.
        
        Checks:
        - No downgrade unless force=true
        - Dependencies remain satisfied
        - Removed capabilities have alternatives
        - Trust level cannot be lowered
        
        Args:
            old_plugin: Current installed plugin metadata
            new_plugin: New plugin metadata from registry
            force: Skip safety checks if true
            
        Returns:
            UpdateCheck with validation result
        """
        if force:
            return UpdateCheck(can_update=True, reason="Update forced")
        
        blocking = []
        warnings = []
        
        # Check version
        old_version = Version(old_plugin.get("version", "0.0.0"))
        new_version = Version(new_plugin.get("version", "0.0.0"))
        
        if new_version < old_version:
            blocking.append(
                f"Cannot downgrade from {old_version} to {new_version} "
                f"without force=true"
            )
        
        # Check dependencies
        new_deps = new_plugin.get("dependencies", [])
        if new_deps:
            unmet_deps = self._check_dependencies(new_deps)
            if unmet_deps:
                blocking.extend([f"Dependency not available: {dep}" for dep in unmet_deps])
        
        # Check capability compatibility
        old_caps = set(old_plugin.get("capabilities_provided", []))
        new_caps = set(new_plugin.get("capabilities_provided", []))
        removed_caps = old_caps - new_caps
        
        if removed_caps and self._runtime:
            unavailable = self._check_capability_alternatives(
                removed_caps,
                old_plugin.get("name", "unknown")
            )
            if unavailable:
                blocking.extend([
                    f"Capability removed with no alternative: {cap}"
                    for cap in unavailable
                ])
        
        # Check trust level
        old_trust = old_plugin.get("trust_level")
        new_trust = new_plugin.get("trust_level")
        if old_trust and new_trust:
            trust_hierarchy = {"core": 3, "publisher": 2, "developer": 1}
            old_level = trust_hierarchy.get(old_trust, 0)
            new_level = trust_hierarchy.get(new_trust, 0)
            
            if new_level < old_level:
                warnings.append(
                    f"Trust level reduced from {old_trust} to {new_trust}"
                )
        
        if blocking:
            return UpdateCheck(
                can_update=False,
                reason="Update not allowed",
                blocking_issues=blocking,
                warnings=warnings
            )
        
        return UpdateCheck(
            can_update=True,
            reason="Update is safe",
            warnings=warnings
        )
    
    def _check_dependencies(self, dependencies: List[str]) -> List[str]:
        """
        Check if dependencies are available/installed.
        
        Returns list of unmet dependencies.
        """
        if not self._runtime:
            return []
        
        pm = getattr(self._runtime, "plugin_manager", None)
        if not pm:
            return []
        
        unmet = []
        for dep in dependencies:
            # Parse dep format: "plugin_name:version_constraint" or "plugin_name"
            if ":" in dep:
                plugin_name = dep.split(":")[0]
            else:
                plugin_name = dep
            
            # Check if plugin is available
            try:
                plugin = pm._plugins.get(plugin_name)
                if not plugin:
                    unmet.append(dep)
            except Exception:
                unmet.append(dep)
        
        return unmet
    
    def _check_capability_alternatives(self,
                                      removed_caps: set,
                                      plugin_name: str) -> set:
        """
        Check if removed capabilities have alternative providers.
        
        Returns set of capabilities with no alternatives.
        """
        if not self._runtime:
            return removed_caps
        
        cap_reg = getattr(self._runtime, "capability_registry", None)
        if not cap_reg:
            return removed_caps
        
        unavailable = set()
        for cap in removed_caps:
            # Check if other providers exist
            try:
                providers = cap_reg._providers.get(cap, [])
                other_providers = [p for p in providers if p.get("plugin") != plugin_name]
                
                if not other_providers:
                    unavailable.add(cap)
            except Exception:
                unavailable.add(cap)
        
        return unavailable
    
    async def check_for_updates(self,
                               current_version: str,
                               available_versions: List[str],
                               channel: str = "stable") -> Optional[str]:
        """
        Check if update is available.
        
        Returns version to update to, or None.
        
        Only suggests non-prerelease updates unless on beta channel.
        """
        from modules.marketplace.semver import VersionResolver
        
        if not available_versions:
            return None
        
        include_prerelease = channel == "beta"
        
        try:
            resolver = VersionResolver(available_versions, include_prerelease)
            
            # Look for newest version greater than current
            newest = resolver.resolve("*") if not include_prerelease else None
            if newest is None:
                # Try with pre-releases
                resolver = VersionResolver(available_versions, include_prerelease=True)
                newest = resolver.resolve("*")
            
            if newest is None:
                return None
            
            current = Version(current_version)
            if newest > current:
                return str(newest)
        
        except Exception as e:
            logger.warning(f"Failed to check for updates: {e}")
            return None
        
        return None
