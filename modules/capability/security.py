"""Capability security checks moved from core to modules layer."""

try:
    from modules.security.trust.legacy_crypto import TrustLevel

    HAS_TRUST_LAYER = True
except ImportError:
    HAS_TRUST_LAYER = False


class CapabilitySecurityError(Exception):
    """Capability security violation."""


TRUST_LEVEL_TO_PRIVILEGE = (
    {
        "core": "core",
        "publisher": "admin",
        "developer": "user",
    }
    if HAS_TRUST_LAYER
    else {}
)

PROTECTED_NAMESPACES = {
    "system.": "core",
    "admin.": "admin",
    "runtime.": "core",
}


def check_capability_namespace_permission(
    capability_id: str,
    plugin_name: str,
    plugin_privilege: str = "user",
) -> None:
    for namespace_prefix, _allowed_privilege in PROTECTED_NAMESPACES.items():
        if capability_id.startswith(namespace_prefix):
            if namespace_prefix == "system.":
                if plugin_privilege != "core":
                    raise CapabilitySecurityError(
                        f"Plugin '{plugin_name}' cannot register system.* capability '{capability_id}': "
                        f"requires CORE trust level (current privilege={plugin_privilege})"
                    )
            elif namespace_prefix == "admin.":
                if plugin_privilege not in ("core", "admin"):
                    raise CapabilitySecurityError(
                        f"Plugin '{plugin_name}' cannot register admin.* capability '{capability_id}': "
                        f"requires PUBLISHER+ trust level (current privilege={plugin_privilege})"
                    )
            elif namespace_prefix == "runtime.":
                if plugin_privilege != "core":
                    raise CapabilitySecurityError(
                        f"Plugin '{plugin_name}' cannot register runtime.* capability '{capability_id}': "
                        f"requires CORE trust level (current privilege={plugin_privilege})"
                    )
            break


def trust_level_to_privilege(trust_level: object = None) -> str:
    if not HAS_TRUST_LAYER or trust_level is None:
        return "user"

    if hasattr(trust_level, "value"):
        level_str = trust_level.value
    else:
        level_str = str(trust_level).lower()

    if level_str == "core":
        return "core"
    if level_str == "publisher":
        return "admin"
    return "user"
