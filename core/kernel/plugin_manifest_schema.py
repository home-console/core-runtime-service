"""
Plugin manifest schema validation.

Validates plugin.json / manifest.json content consumed by the plugin loader.
Lives in core.kernel so that plugin_loader can import it without crossing
the core→modules boundary.
"""

from typing import Any, Dict
import re


class ValidationError(Exception):
    """Plugin manifest validation error."""
    pass


def validate_plugin_name(name: str) -> None:
    if not name:
        raise ValidationError("Plugin name is empty")
    if ".." in name or "/" in name or "\\" in name:
        raise ValidationError("Plugin name contains path traversal characters")
    if not name.isidentifier() or not name.islower():
        raise ValidationError(f"Plugin name '{name}' must be lowercase identifier (snake_case)")


def validate_version(version: str) -> None:
    if not re.match(r"^\d+\.\d+\.\d+(-[a-zA-Z0-9]+)?$", version):
        raise ValidationError(f"Invalid version format: {version} (must be semantic: X.Y.Z)")


def validate_plugin_json(data: Any) -> Dict[str, Any]:
    """
    Validate plugin.json content and apply defaults.

    Required fields: name, version, description, author, class_path

    Returns validated data with defaults applied.
    Raises ValidationError on failure.
    """
    if not isinstance(data, dict):
        raise ValidationError("plugin.json must be a JSON object")

    required_fields = ["name", "version", "description", "author", "class_path"]
    for field in required_fields:
        if field not in data:
            raise ValidationError(f"Missing required field: {field}")

    name = data.get("name")
    if not isinstance(name, str) or not name:
        raise ValidationError("Field 'name' must be non-empty string")
    validate_plugin_name(name)

    version = data.get("version")
    if not isinstance(version, str) or not version:
        raise ValidationError("Field 'version' must be non-empty string")
    validate_version(version)

    for field in ["description", "author"]:
        value = data.get(field)
        if not isinstance(value, str) or not value:
            raise ValidationError(f"Field '{field}' must be non-empty string")

    class_path = data.get("class_path")
    if not isinstance(class_path, str) or not class_path:
        raise ValidationError("class_path must be non-empty string")
    if "." not in class_path:
        raise ValidationError(
            f"class_path '{class_path}' must be a dotted path "
            "(e.g. 'plugins.my_plugin.plugin.MyPlugin')"
        )

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

    deps = data.get("dependencies", [])
    if not isinstance(deps, list):
        raise ValidationError("Field 'dependencies' must be array")
    for dep in deps:
        if not isinstance(dep, str):
            raise ValidationError("Dependency must be string")

    requires = data.get("requires", [])
    if not isinstance(requires, list):
        raise ValidationError("Field 'requires' must be array")
    for req in requires:
        if not isinstance(req, str):
            raise ValidationError("Requirement must be string")

    if not isinstance(data["is_integration"], bool):
        raise ValidationError("Field 'is_integration' must be boolean")

    flags = data.get("integration_flags", [])
    if not isinstance(flags, list):
        raise ValidationError("Field 'integration_flags' must be array")
    for flag in flags:
        if not isinstance(flag, str):
            raise ValidationError("Integration flag must be string")

    valid_modes = ["in_process", "subprocess", "container"]
    if data["execution_mode"] not in valid_modes:
        raise ValidationError(f"execution_mode must be one of {valid_modes}")

    if not isinstance(data["user_facing"], bool):
        raise ValidationError("Field 'user_facing' must be boolean")

    return data
