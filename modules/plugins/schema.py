"""
Plugin JSON schema validation and utilities.

Validates plugin.json manifest format.
Ensures plugin packages meet minimal requirements.

Schema reflects the actual fields consumed by:
- core/kernel/plugin_loader.py (class_path, name, dependencies)
- core/kernel/plugin_manager.py (is_integration, integration_*, type, role, beta, experimental)
"""

from typing import Dict, Any, List


# Minimal plugin.json schema — reflects fields actually used by PluginLoader/PluginManager
PLUGIN_JSON_SCHEMA = {
    "type": "object",
    "required": ["name", "version", "description", "author", "class_path"],
    "properties": {
        # --- Required fields ---
        "name": {
            "type": "string",
            "minLength": 1,
            "maxLength": 100,
            "pattern": "^[a-z_][a-z0-9_]*$"
        },
        "version": {
            "type": "string",
            "pattern": r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$"
        },
        "description": {
            "type": "string",
            "minLength": 1,
            "maxLength": 500
        },
        "author": {
            "type": "string",
            "minLength": 1,
            "maxLength": 200
        },
        "class_path": {
            "type": "string",
            "minLength": 1,
            "description": "Dotted path to the plugin class, e.g. 'plugins.my_plugin.plugin.MyPlugin'"
        },

        # --- Dependency fields ---
        "dependencies": {
            "type": "array",
            "items": {"type": "string"},
            "default": [],
            "description": "List of plugin names this plugin depends on"
        },
        "requires": {
            "type": "array",
            "items": {"type": "string"},
            "default": [],
            "description": "Alias for dependencies (alternative name)"
        },

        # --- Integration fields (plugin_manager.py) ---
        "is_integration": {
            "type": "boolean",
            "default": False,
            "description": "Whether this plugin is a third-party integration"
        },
        "integration_name": {
            "type": "string",
            "default": None,
            "description": "Human-readable integration name"
        },
        "integration_flags": {
            "type": "array",
            "items": {"type": "string"},
            "default": [],
            "description": "Flags like requires_oauth, requires_config"
        },

        # --- Metadata fields ---
        "type": {
            "type": "string",
            "default": "integration",
            "description": "Plugin type: integration, authentication, oauth, etc."
        },
        "role": {
            "type": "string",
            "default": None,
            "description": "Plugin role, e.g. capability_provider"
        },
        "capability": {
            "type": "string",
            "default": None,
            "description": "Capability identifier provided by this plugin"
        },
        "user_facing": {
            "type": "boolean",
            "default": True,
            "description": "Whether this plugin has user-facing UI"
        },
        "execution_mode": {
            "type": "string",
            "enum": ["in_process", "subprocess", "container"],
            "default": "in_process",
            "description": "How the plugin is executed"
        },
        "license": {
            "type": "string",
            "default": None,
            "description": "License identifier, e.g. MIT"
        },
        "config": {
            "type": "object",
            "default": {},
            "description": "Default configuration for the plugin"
        },
        "documentation": {
            "type": "object",
            "default": {},
            "description": "Links to documentation files"
        },
        "provides": {
            "type": "object",
            "default": {},
            "description": "Services, HTTP endpoints, events provided by this plugin"
        },

        # --- Lifecycle flags ---
        "beta": {
            "type": "boolean",
            "default": False,
            "description": "Whether this plugin is in beta"
        },
        "experimental": {
            "type": "boolean",
            "default": False,
            "description": "Whether this plugin is experimental"
        },
        "_disabled": {
            "type": "boolean",
            "default": False,
            "description": "Internal: skip this plugin during loading"
        }
    }
}


class ValidationError(Exception):
    """Plugin validation error."""
    pass


def validate_plugin_name(name: str) -> None:
    """
    Validate plugin name format.
    
    Must be:
    - Valid Python identifier (snake_case)
    - No path traversal attempts
    - No special characters
    """
    if not name:
        raise ValidationError("Plugin name is empty")
    
    if ".." in name or "/" in name or "\\" in name:
        raise ValidationError("Plugin name contains path traversal characters")
    
    if not name.isidentifier() or not name.islower():
        raise ValidationError(f"Plugin name '{name}' must be lowercase identifier (snake_case)")


def validate_version(version: str) -> None:
    """Validate semantic version format."""
    import re
    if not re.match(r"^\d+\.\d+\.\d+(-[a-zA-Z0-9]+)?$", version):
        raise ValidationError(f"Invalid version format: {version} (must be semantic: X.Y.Z)")


def validate_plugin_json(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate plugin.json content.

    Required fields: name, version, description, author, class_path
    All other fields are optional with sensible defaults.

    Args:
        data: Parsed plugin.json dictionary

    Returns:
        Validated data with defaults applied

    Raises:
        ValidationError: if validation fails
    """
    if not isinstance(data, dict):
        raise ValidationError("plugin.json must be a JSON object")

    # --- Check required fields ---
    required_fields = ["name", "version", "description", "author", "class_path"]
    for field in required_fields:
        if field not in data:
            raise ValidationError(f"Missing required field: {field}")

    # --- Validate name ---
    name = data.get("name")
    if not isinstance(name, str) or not name:
        raise ValidationError("Field 'name' must be non-empty string")
    validate_plugin_name(name)

    # --- Validate version ---
    version = data.get("version")
    if not isinstance(version, str) or not version:
        raise ValidationError("Field 'version' must be non-empty string")
    validate_version(version)

    # --- Validate string fields ---
    for field in ["description", "author"]:
        value = data.get(field)
        if not isinstance(value, str) or not value:
            raise ValidationError(f"Field '{field}' must be non-empty string")

    # --- Validate class_path (dotted Python path) ---
    class_path = data.get("class_path")
    if not isinstance(class_path, str) or not class_path:
        raise ValidationError("class_path must be non-empty string")
    if "." not in class_path:
        raise ValidationError(f"class_path '{class_path}' must be a dotted path (e.g. 'plugins.my_plugin.plugin.MyPlugin')")

    # --- Optional fields with defaults ---
    data.setdefault("dependencies", [])
    data.setdefault("requires", [])
    data.setdefault("is_integration", False)
    data.setdefault("integration_name", None)
    data.setdefault("integration_flags", [])
    data.setdefault("type", "integration")
    data.setdefault("role", None)
    data.setdefault("capability", None)
    data.setdefault("user_facing", True)
    data.setdefault("execution_mode", "in_process")
    data.setdefault("license", None)
    data.setdefault("config", {})
    data.setdefault("documentation", {})
    data.setdefault("provides", {})
    data.setdefault("beta", False)
    data.setdefault("experimental", False)
    data.setdefault("_disabled", False)

    # --- Validate dependencies ---
    deps = data.get("dependencies", [])
    if not isinstance(deps, list):
        raise ValidationError("Field 'dependencies' must be array")
    for dep in deps:
        if not isinstance(dep, str):
            raise ValidationError("Dependency must be string")

    # --- Validate requires (alias for dependencies) ---
    requires = data.get("requires", [])
    if not isinstance(requires, list):
        raise ValidationError("Field 'requires' must be array")
    for req in requires:
        if not isinstance(req, str):
            raise ValidationError("Requirement must be string")

    # --- Validate integration flags ---
    if not isinstance(data["is_integration"], bool):
        raise ValidationError("Field 'is_integration' must be boolean")

    flags = data.get("integration_flags", [])
    if not isinstance(flags, list):
        raise ValidationError("Field 'integration_flags' must be array")
    for flag in flags:
        if not isinstance(flag, str):
            raise ValidationError("Integration flag must be string")

    # --- Validate execution_mode ---
    valid_modes = ["in_process", "subprocess", "container"]
    if data["execution_mode"] not in valid_modes:
        raise ValidationError(f"execution_mode must be one of {valid_modes}")

    # --- Validate user_facing ---
    if not isinstance(data["user_facing"], bool):
        raise ValidationError("Field 'user_facing' must be boolean")

    return data
