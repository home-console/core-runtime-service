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
    Validate plugin.json (delegates to core.kernel.plugin_manifest_schema).

    Raises modules.plugins.schema.ValidationError on failure.
    """
    from core.kernel.plugin_manifest_schema import (
        ValidationError as KernelValidationError,
    )
    from core.kernel.plugin_manifest_schema import (
        validate_plugin_json as _validate_kernel,
    )

    try:
        return _validate_kernel(data)
    except KernelValidationError as e:
        raise ValidationError(str(e)) from e
