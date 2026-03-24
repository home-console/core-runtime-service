"""
Secret Access Policy for Vault.

Controls which plugins can access which secret namespaces.
- is_allowed(plugin_name, namespace) -> bool
- Strict whitelist model
- Configurable via YAML
"""

from typing import Dict, Set, List
from dataclasses import dataclass, field


@dataclass
class SecretAccessPolicy:
    """
    Secret access control policy.
    
    Whitelist model:
    - By default, all access is DENIED
    - Must explicitly allow (plugin, namespace)
    - Used by SecretStore.get/put/delete
    """
    
    # Map: plugin_name -> set of allowed namespaces
    _allowed: Dict[str, Set[str]] = field(default_factory=dict)
    
    def allow(self, plugin_name: str, namespaces: List[str]) -> None:
        """
        Grant plugin access to namespaces.
        
        Args:
            plugin_name: plugin identifier
            namespaces: list of namespace strings
        """
        if plugin_name not in self._allowed:
            self._allowed[plugin_name] = set()
        
        for ns in namespaces:
            self._allowed[plugin_name].add(ns)
    
    def deny(self, plugin_name: str, namespace: str) -> None:
        """
        Revoke plugin access to namespace.
        
        Args:
            plugin_name: plugin identifier
            namespace: namespace string
        """
        if plugin_name in self._allowed:
            self._allowed[plugin_name].discard(namespace)
    
    def is_allowed(self, plugin_name: str, namespace: str) -> bool:
        """
        Check if plugin can access namespace.
        
        Default: DENY
        Only allows if explicitly granted.
        
        Args:
            plugin_name: plugin identifier
            namespace: namespace string
            
        Returns:
            True if allowed, False otherwise
        """
        if plugin_name not in self._allowed:
            return False
        
        return namespace in self._allowed[plugin_name]
    
    def get_allowed_namespaces(self, plugin_name: str) -> Set[str]:
        """Get all allowed namespaces for plugin."""
        return self._allowed.get(plugin_name, set()).copy()
    
    def revoke_all(self, plugin_name: str) -> None:
        """Revoke all access for plugin."""
        if plugin_name in self._allowed:
            self._allowed[plugin_name].clear()
    
    def to_dict(self) -> Dict[str, List[str]]:
        """Serialize to dict."""
        return {
            plugin: sorted(list(namespaces))
            for plugin, namespaces in self._allowed.items()
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "SecretAccessPolicy":
        """Deserialize from dict."""
        policy = cls()
        for plugin_name, namespaces in data.items():
            if isinstance(namespaces, list):
                policy.allow(plugin_name, namespaces)
        return policy


# Default policies for common plugins

def create_default_policy() -> SecretAccessPolicy:
    """
    Create default policy for core plugins.
    
    Only grants minimum necessary access.
    """
    policy = SecretAccessPolicy()
    
    # Core runtime: access to all (internal)
    policy.allow("core.runtime", [
        "secrets.app_key",
        "secrets.db_password",
        "secrets.api_key",
    ])
    
    # OAuth plugin: access to oauth tokens only
    policy.allow("oauth", [
        "secrets.oauth_token",
    ])
    
    # Trust plugin: access to trust store
    policy.allow("trust", [
        "trust_store",
    ])
    
    # Agent controller: agent-specific secrets
    policy.allow("agent_control", [
        "secrets.agent_keys",
    ])
    
    return policy


# Enforcement for SecretStore
class SecretAccessDenied(PermissionError):
    """Plugin denied access to secret namespace."""
    
    def __init__(self, plugin_name: str, namespace: str):
        self.plugin_name = plugin_name
        self.namespace = namespace
        super().__init__(
            f"Plugin '{plugin_name}' denied access to namespace '{namespace}'"
        )
