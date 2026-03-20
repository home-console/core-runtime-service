"""
Capability Security Module — trust-aware capability registration (Step 11, D2).

Проверяет безопасность при регистрации capabilities:
- Защита system.*, admin.*, runtime.* namespaces
- Trust level enforcement based on plugin privilege
- Capability security error handling
"""

try:
    from core.security.trust.legacy_crypto import TrustLevel
    HAS_TRUST_LAYER = True
except ImportError:
    HAS_TRUST_LAYER = False


class CapabilitySecurityError(Exception):
    """Capability security violation."""
    pass


# Namespace protection rules
# Step 11: Trust level mapping for capability registration
# - CORE (3) → can register system.*, admin.*, runtime.*
# - PUBLISHER (2) → can register admin.* but not system.*, runtime.*
# - DEVELOPER (1) → cannot register system.*, admin.*, runtime.*
# 
# Mapping to privilege levels:
# - trust_level_to_privilege: TrustLevel → plugin_privilege
TRUST_LEVEL_TO_PRIVILEGE = {
    "core": "core",        # TrustLevel.CORE (3) 
    "publisher": "admin",  # TrustLevel.PUBLISHER (2)
    "developer": "user",   # TrustLevel.DEVELOPER (1)
} if HAS_TRUST_LAYER else {}

PROTECTED_NAMESPACES = {
    "system.": "core",    # Only CORE trust level (core privilege)
    "admin.": "admin",    # Only PUBLISHER+ trust level (admin privilege)
    "runtime.": "core",   # Only CORE trust level (core privilege)
}


def check_capability_namespace_permission(
    capability_id: str,
    plugin_name: str,
    plugin_privilege: str = "user"
) -> None:
    """
    Check if plugin has permission to register this capability.
    
    Step 11: Trust level enforcement for protected capabilities
    - system.* capabilities: ONLY CORE trusted keys (privilege=core)
    - admin.* capabilities: PUBLISHER and CORE keys (privilege=admin or core)
    - runtime.* capabilities: ONLY CORE trusted keys (privilege=core)
    - Custom capabilities: Any trusted plugin (privilege=admin, core, or user)
    
    Args:
        capability_id: Capability ID (e.g., "system.reboot")
        plugin_name: Plugin trying to register it
        plugin_privilege: Plugin privilege level ("core", "admin", "user")
            Maps from TrustLevel:
            - "core" ← TrustLevel.CORE
            - "admin" ← TrustLevel.PUBLISHER
            - "user" ← TrustLevel.DEVELOPER or unsigned
        
    Raises:
        CapabilitySecurityError: If plugin lacks permission
    """
    # Check protected namespaces
    for namespace_prefix, allowed_privilege in PROTECTED_NAMESPACES.items():
        if capability_id.startswith(namespace_prefix):
            # Step 11: Enhanced checking with trust level clarity
            if namespace_prefix == "system.":
                # system.* → only CORE level (privilege="core")
                if plugin_privilege != "core":
                    raise CapabilitySecurityError(
                        f"Plugin '{plugin_name}' cannot register system.* capability '{capability_id}': "
                        f"requires CORE trust level (current privilege={plugin_privilege})"
                    )
            elif namespace_prefix == "admin.":
                # admin.* → PUBLISHER+ level (privilege="admin" or "core")
                if plugin_privilege not in ("core", "admin"):
                    raise CapabilitySecurityError(
                        f"Plugin '{plugin_name}' cannot register admin.* capability '{capability_id}': "
                        f"requires PUBLISHER+ trust level (current privilege={plugin_privilege})"
                    )
            elif namespace_prefix == "runtime.":
                # runtime.* → only CORE level (privilege="core")
                if plugin_privilege != "core":
                    raise CapabilitySecurityError(
                        f"Plugin '{plugin_name}' cannot register runtime.* capability '{capability_id}': "
                        f"requires CORE trust level (current privilege={plugin_privilege})"
                    )
            break


def trust_level_to_privilege(trust_level: object = None) -> str:
    """
    Step 11: Convert TrustLevel enum to privilege level for capability registration.
    
    Mapping:
    - TrustLevel.CORE ("core") → "core"
    - TrustLevel.PUBLISHER ("publisher") → "admin"
    - TrustLevel.DEVELOPER ("developer") → "user"
    - None (unsigned plugin) → "user"
    
    Args:
        trust_level: TrustLevel enum value or None
        
    Returns:
        privilege level string ("core", "admin", or "user")
    """
    if not HAS_TRUST_LAYER or trust_level is None:
        return "user"  # Default for unsigned plugins
    
    # TrustLevel enum has values: "core", "publisher", "developer"
    # Or it could be passed as enum member
    if hasattr(trust_level, 'value'):
        level_str = trust_level.value
    else:
        level_str = str(trust_level).lower()
    
    if level_str == "core":
        return "core"
    elif level_str == "publisher":
        return "admin"
    else:  # "developer" or anything else
        return "user"
