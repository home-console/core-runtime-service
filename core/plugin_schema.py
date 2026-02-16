"""
Plugin JSON schema validation and utilities.

Validates plugin.json manifest format.
Ensures plugin packages meet minimal requirements.
"""

from typing import Dict, Any, List
import json


# Minimal plugin.json schema
PLUGIN_JSON_SCHEMA = {
    "type": "object",
    "required": ["name", "version", "description", "author", "entrypoint"],
    "properties": {
        "name": {
            "type": "string",
            "minLength": 1,
            "maxLength": 100,
            "pattern": "^[a-z_][a-z0-9_]*$"  # snake_case identifier
        },
        "version": {
            "type": "string",
            "pattern": r"^\d+\.\d+\.\d+(-[a-zA-Z0-9]+)?$"  # semantic versioning
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
        "entrypoint": {
            "type": "string",
            "minLength": 1
        },
        "capabilities_provided": {
            "type": "array",
            "items": {"type": "string"},
            "default": []
        },
        "capabilities_required": {
            "type": "array",
            "items": {"type": "string"},
            "default": []
        },
        "dependencies": {
            "type": "array",
            "items": {"type": "string"},
            "default": []
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
    
    Args:
        data: Parsed plugin.json dictionary
        
    Returns:
        Validated data with defaults applied
        
    Raises:
        ValidationError: if validation fails
    """
    if not isinstance(data, dict):
        raise ValidationError("plugin.json must be a JSON object")
    
    # Check required fields
    required_fields = ["name", "version", "description", "author", "entrypoint"]
    for field in required_fields:
        if field not in data:
            raise ValidationError(f"Missing required field: {field}")
    
    # Validate name
    name = data.get("name")
    validate_plugin_name(name)
    
    # Validate version
    version = data.get("version")
    validate_version(version)
    
    # Validate string fields
    for field in ["description", "author"]:
        value = data.get(field)
        if not isinstance(value, str) or not value:
            raise ValidationError(f"Field '{field}' must be non-empty string")
    
    # Validate entrypoint (should be valid Python module path)
    entrypoint = data.get("entrypoint")
    if not isinstance(entrypoint, str) or not entrypoint:
        raise ValidationError("entrypoint must be non-empty string")
    
    # Optional fields with defaults
    data.setdefault("capabilities_provided", [])
    data.setdefault("capabilities_required", [])
    data.setdefault("dependencies", [])
    
    # Validate capability lists
    for field in ["capabilities_provided", "capabilities_required"]:
        value = data.get(field, [])
        if not isinstance(value, list):
            raise ValidationError(f"Field '{field}' must be array")
        for cap in value:
            if not isinstance(cap, str):
                raise ValidationError(f"Capability in '{field}' must be string")
    
    # Validate dependencies
    deps = data.get("dependencies", [])
    if not isinstance(deps, list):
        raise ValidationError("Field 'dependencies' must be array")
    for dep in deps:
        if not isinstance(dep, str):
            raise ValidationError("Dependency must be string")
    
    return data
