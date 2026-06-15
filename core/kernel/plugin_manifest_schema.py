"""
Plugin manifest schema validation.

Validates plugin.json / manifest.json for core loader and marketplace publish.
Optional sections: ui / ui_contributions, cli / cli_subcommands, skills
(declarations for modules/skills — not modules/agent control plane).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set

_SEMVER = re.compile(r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$")
_SNAKE = re.compile(r"^[a-z_][a-z0-9_]*$")
_ROUTE_PATH = re.compile(r"^/[a-zA-Z0-9_./-]*$")

# Server-driven UI (§1.4 new-tasks.md [1]); legacy `module` = publish-time zip check only.
UI_CONTRIBUTION_TYPES = frozenset({"settings", "metric", "table"})


class ValidationError(Exception):
    """Plugin manifest validation error."""


def validate_plugin_name(name: str) -> None:
    if not name:
        raise ValidationError("Plugin name is empty")
    if ".." in name or "/" in name or "\\" in name:
        raise ValidationError("Plugin name contains path traversal characters")
    if not name.isidentifier() or not name.islower():
        raise ValidationError(f"Plugin name '{name}' must be lowercase identifier (snake_case)")


def validate_namespace(value: str) -> None:
    """Namespace is a dot-separated hierarchy of snake_case identifiers
    (e.g. "acme.device_auth"), used as a prefix for service/event registration."""
    if not value:
        raise ValidationError("Namespace is empty")
    if ".." in value or "/" in value or "\\" in value:
        raise ValidationError("Namespace contains path traversal characters")
    for part in value.split("."):
        if not part or not part.isidentifier() or not part.islower():
            raise ValidationError(
                f"Namespace '{value}' must be dot-separated lowercase identifiers (snake_case)"
            )


def validate_version(version: str) -> None:
    if not _SEMVER.match(version):
        raise ValidationError(f"Invalid version format: {version} (must be semantic: X.Y.Z)")


def _require_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"Field '{field}' must be non-empty string")
    return value.strip()


def _validate_string_list(value: Any, field: str) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValidationError(f"Field '{field}' must be array")
    out: List[str] = []
    for i, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ValidationError(f"Field '{field}[{i}]' must be non-empty string")
        out.append(item.strip())
    return out


def _validate_relative_module(path: str, *, context: str) -> str:
    p = path.strip().replace("\\", "/")
    if not p:
        raise ValidationError(f"{context}: module path is empty")
    if p.startswith("/") or "://" in p:
        raise ValidationError(f"{context}: module must be a relative path, got {path!r}")
    parts = p.split("/")
    if any(part == ".." for part in parts):
        raise ValidationError(f"{context}: module path must not contain '..'")
    return p


def _validate_contribution_id(value: str, *, context: str) -> str:
    vid = _require_str(value, context)
    if not _SNAKE.match(vid):
        raise ValidationError(f"{context}: id must be snake_case, got {value!r}")
    return vid


def _validate_optional_object(value: Any, *, context: str) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValidationError(f"{context} must be an object")
    return dict(value)


def _validate_optional_service(item: Dict[str, Any], *, context: str, required: bool) -> Optional[str]:
    raw = item.get("service")
    if raw is None:
        if required:
            raise ValidationError(f"{context}: 'service' is required")
        return None
    svc = _require_str(raw, f"{context}.service")
    return svc


def _validate_ui_contribution_keys(
    item: Dict[str, Any],
    *,
    context: str,
    allowed: set[str],
) -> None:
    extra = set(item.keys()) - allowed
    if extra:
        raise ValidationError(f"{context}: unknown keys: {', '.join(sorted(extra))}")


def _validate_ui_page(item: Any, index: int) -> Dict[str, Any]:
    if not isinstance(item, dict):
        raise ValidationError(f"ui.pages[{index}] must be an object")
    ctx = f"ui.pages[{index}]"
    path = _require_str(item.get("path"), f"{ctx}.path")
    if not _ROUTE_PATH.match(path):
        raise ValidationError(f"{ctx}.path must start with '/' and contain safe characters")

    page_type = item.get("type")
    module_raw = item.get("module")
    has_type = isinstance(page_type, str) and bool(page_type.strip())
    has_module = isinstance(module_raw, str) and bool(str(module_raw).strip())

    if has_type and has_module:
        raise ValidationError(
            f"{ctx}: use either 'type' (server-driven) or 'module' (legacy publish), not both"
        )

    if has_type:
        t = str(page_type).strip()
        if t not in UI_CONTRIBUTION_TYPES:
            raise ValidationError(
                f"{ctx}.type must be one of: {', '.join(sorted(UI_CONTRIBUTION_TYPES))}"
            )
        out: Dict[str, Any] = {"path": path, "type": t}
        cfg = _validate_optional_object(item.get("config"), context=f"{ctx}.config")
        if cfg is not None:
            out["config"] = cfg
        schema = _validate_optional_object(item.get("config_schema"), context=f"{ctx}.config_schema")
        if schema is not None:
            out["config_schema"] = schema
        svc = _validate_optional_service(item, context=ctx, required=(t == "metric"))
        if svc is not None:
            out["service"] = svc
        if "title" in item and item["title"] is not None:
            out["title"] = _require_str(item["title"], f"{ctx}.title")
        _validate_ui_contribution_keys(
            item,
            context=ctx,
            allowed={"path", "type", "config", "config_schema", "service", "title"},
        )
        return out

    if has_module:
        module = _validate_relative_module(
            _require_str(module_raw, f"{ctx}.module"),
            context=ctx,
        )
        _validate_ui_contribution_keys(item, context=ctx, allowed={"path", "module", "title"})
        out = {"path": path, "module": module}
        if "title" in item and item["title"] is not None:
            out["title"] = _require_str(item["title"], f"{ctx}.title")
        return out

    raise ValidationError(f"{ctx}: require 'type' (server-driven) or 'module' (legacy publish)")


def _validate_ui_widget(item: Any, index: int, *, kind: str) -> Dict[str, Any]:
    if not isinstance(item, dict):
        raise ValidationError(f"ui.{kind}[{index}] must be an object")
    ctx = f"ui.{kind}[{index}]"
    wid = _validate_contribution_id(item.get("id"), context=f"{ctx}.id")

    page_type = item.get("type")
    module_raw = item.get("module")
    has_type = isinstance(page_type, str) and bool(page_type.strip())
    has_module = isinstance(module_raw, str) and bool(str(module_raw).strip())

    if has_type and has_module:
        raise ValidationError(
            f"{ctx}: use either 'type' (server-driven) or 'module' (legacy publish), not both"
        )

    if has_type:
        t = str(page_type).strip()
        if t not in UI_CONTRIBUTION_TYPES:
            raise ValidationError(
                f"{ctx}.type must be one of: {', '.join(sorted(UI_CONTRIBUTION_TYPES))}"
            )
        out: Dict[str, Any] = {"id": wid, "type": t}
        cfg = _validate_optional_object(item.get("config"), context=f"{ctx}.config")
        if cfg is not None:
            out["config"] = cfg
        schema = _validate_optional_object(item.get("config_schema"), context=f"{ctx}.config_schema")
        if schema is not None:
            out["config_schema"] = schema
        svc = _validate_optional_service(item, context=ctx, required=(t in ("metric", "table")))
        if svc is not None:
            out["service"] = svc
        if "title" in item and item["title"] is not None:
            out["title"] = _require_str(item["title"], f"{ctx}.title")
        _validate_ui_contribution_keys(
            item,
            context=ctx,
            allowed={"id", "type", "config", "config_schema", "service", "title"},
        )
        return out

    if has_module:
        module = _validate_relative_module(
            _require_str(module_raw, f"{ctx}.module"),
            context=ctx,
        )
        _validate_ui_contribution_keys(item, context=ctx, allowed={"id", "module", "title"})
        out: Dict[str, Any] = {"id": wid, "module": module}
        if "title" in item and item["title"] is not None:
            out["title"] = _require_str(item["title"], f"{ctx}.title")
        return out

    raise ValidationError(f"{ctx}: require 'type' (server-driven) or 'module' (legacy publish)")


def _validate_ui_block(ui: Any) -> Dict[str, Any]:
    if not isinstance(ui, dict):
        raise ValidationError("ui section must be an object")
    pages_raw = ui.get("pages", [])
    widgets_raw = ui.get("widgets", [])
    cards_raw = ui.get("dashboard_cards", [])

    if not isinstance(pages_raw, list):
        raise ValidationError("ui.pages must be array")
    if not isinstance(widgets_raw, list):
        raise ValidationError("ui.widgets must be array")
    if not isinstance(cards_raw, list):
        raise ValidationError("ui.dashboard_cards must be array")

    pages = [_validate_ui_page(p, i) for i, p in enumerate(pages_raw)]
    widgets = [_validate_ui_widget(w, i, kind="widgets") for i, w in enumerate(widgets_raw)]
    cards = [_validate_ui_widget(c, i, kind="dashboard_cards") for i, c in enumerate(cards_raw)]

    extra = set(ui.keys()) - {"pages", "widgets", "dashboard_cards"}
    if extra:
        raise ValidationError(f"ui: unknown keys: {', '.join(sorted(extra))}")

    return {"pages": pages, "widgets": widgets, "dashboard_cards": cards}


def _validate_cli_subcommand(item: Any, index: int) -> Dict[str, str]:
    if not isinstance(item, dict):
        raise ValidationError(f"cli.subcommands[{index}] must be an object")
    name = _validate_contribution_id(item.get("name"), context=f"cli.subcommands[{index}].name")
    module = _validate_relative_module(
        _require_str(item.get("module"), f"cli.subcommands[{index}].module"),
        context=f"cli.subcommands[{index}]",
    )
    out: Dict[str, str] = {"name": name, "module": module}
    if "description" in item and item["description"] is not None:
        out["description"] = _require_str(item["description"], f"cli.subcommands[{index}].description")
    extra = set(item.keys()) - {"name", "module", "description"}
    if extra:
        raise ValidationError(f"cli.subcommands[{index}]: unknown keys: {', '.join(sorted(extra))}")
    return out


def _validate_cli_block(cli: Any) -> Dict[str, Any]:
    if not isinstance(cli, dict):
        raise ValidationError("cli section must be an object")
    sub_raw = cli.get("subcommands", [])
    if not isinstance(sub_raw, list):
        raise ValidationError("cli.subcommands must be array")
    subcommands = [_validate_cli_subcommand(s, i) for i, s in enumerate(sub_raw)]
    extra = set(cli.keys()) - {"subcommands"}
    if extra:
        raise ValidationError(f"cli: unknown keys: {', '.join(sorted(extra))}")
    return {"subcommands": subcommands}


def _validate_skill(item: Any, index: int) -> Dict[str, str]:
    if not isinstance(item, dict):
        raise ValidationError(f"skills[{index}] must be an object")
    name = _validate_contribution_id(item.get("name"), context=f"skills[{index}].name")
    intent = _require_str(item.get("intent"), f"skills[{index}].intent")
    out: Dict[str, str] = {"name": name, "intent": intent}
    if "description" in item and item["description"] is not None:
        out["description"] = _require_str(item["description"], f"skills[{index}].description")
    if "service" in item and item["service"] is not None:
        svc = _require_str(item["service"], f"skills[{index}].service")
        if not svc:
            raise ValidationError(f"skills[{index}].service must be non-empty string")
        out["service"] = svc
    extra = set(item.keys()) - {"name", "intent", "description", "service"}
    if extra:
        raise ValidationError(f"skills[{index}]: unknown keys: {', '.join(sorted(extra))}")
    return out


def _validate_skills(skills: Any) -> List[Dict[str, str]]:
    if not isinstance(skills, list):
        raise ValidationError("skills must be array")
    return [_validate_skill(s, i) for i, s in enumerate(skills)]


def _normalize_contributions(data: Dict[str, Any]) -> None:
    """Merge legacy aliases into canonical ui / cli keys."""
    if "ui_contributions" in data:
        if "ui" in data:
            raise ValidationError("use either 'ui' or 'ui_contributions', not both")
        data["ui"] = data.pop("ui_contributions")

    if "cli_subcommands" in data:
        if "cli" in data:
            raise ValidationError("use either 'cli.subcommands' or 'cli_subcommands', not both")
        raw = data.pop("cli_subcommands")
        if not isinstance(raw, list):
            raise ValidationError("cli_subcommands must be array")
        data["cli"] = {"subcommands": raw}

    if "agent_skills" in data:
        raise ValidationError("use 'skills' instead of 'agent_skills'")


def collect_manifest_module_paths(manifest: Dict[str, Any]) -> Set[str]:
    """Relative module paths referenced by ui/cli sections (for archive checks)."""
    paths: Set[str] = set()
    ui = manifest.get("ui")
    if isinstance(ui, dict):
        for section in ("pages", "widgets", "dashboard_cards"):
            for item in ui.get(section) or []:
                if isinstance(item, dict) and isinstance(item.get("module"), str):
                    mod = item["module"].strip().replace("\\", "/").lstrip("./")
                    if mod:
                        paths.add(mod)
    cli = manifest.get("cli")
    if isinstance(cli, dict):
        for item in cli.get("subcommands") or []:
            if isinstance(item, dict) and isinstance(item.get("module"), str):
                paths.add(item["module"].strip().replace("\\", "/").lstrip("./"))
    return paths


def validate_plugin_json(data: Any) -> Dict[str, Any]:
    """
    Validate plugin.json and apply defaults.

    Required: name, version, description, author, class_path.
    Optional: dependencies, namespace, provides_*, ui, cli, skills, …
    """
    if not isinstance(data, dict):
        raise ValidationError("plugin.json must be a JSON object")

    _normalize_contributions(data)

    required_fields = ["name", "version", "description", "author", "class_path"]
    for field in required_fields:
        if field not in data:
            raise ValidationError(f"Missing required field: {field}")

    name = _require_str(data.get("name"), "name")
    validate_plugin_name(name)
    data["name"] = name

    version = _require_str(data.get("version"), "version")
    validate_version(version)
    data["version"] = version

    data["description"] = _require_str(data.get("description"), "description")
    data["author"] = _require_str(data.get("author"), "author")

    class_path = _require_str(data.get("class_path"), "class_path")
    if "." not in class_path:
        raise ValidationError(
            f"class_path '{class_path}' must be a dotted path "
            "(e.g. 'plugins.my_plugin.plugin.MyPlugin')"
        )
    data["class_path"] = class_path

    data["dependencies"] = _validate_string_list(data.get("dependencies"), "dependencies")
    data["requires"] = _validate_string_list(data.get("requires"), "requires")

    if "namespace" in data and data["namespace"] is not None:
        ns = _require_str(data["namespace"], "namespace")
        validate_namespace(ns)
        data["namespace"] = ns

    for field in (
        "allowed_services",
        "provides_services",
        "provides_events",
        "subscribes_events",
        "provides_operations",
        "storage_namespaces",
    ):
        if field in data:
            data[field] = _validate_string_list(data.get(field), field)

    data.setdefault("is_integration", False)
    if not isinstance(data["is_integration"], bool):
        raise ValidationError("Field 'is_integration' must be boolean")

    data.setdefault("integration_flags", [])
    data["integration_flags"] = _validate_string_list(data.get("integration_flags"), "integration_flags")

    data.setdefault("dynamic_service_registration", False)
    if not isinstance(data["dynamic_service_registration"], bool):
        raise ValidationError("Field 'dynamic_service_registration' must be boolean")

    data.setdefault("type", "integration")
    if not isinstance(data["type"], str) or not data["type"].strip():
        raise ValidationError("Field 'type' must be non-empty string")

    data.setdefault("user_facing", True)
    if not isinstance(data["user_facing"], bool):
        raise ValidationError("Field 'user_facing' must be boolean")

    data.setdefault("execution_mode", "in_process")
    valid_modes = ("in_process", "subprocess", "container")
    if data["execution_mode"] not in valid_modes:
        raise ValidationError(f"execution_mode must be one of {valid_modes}")

    for obj_field in ("config", "documentation", "provides"):
        val = data.get(obj_field)
        if val is None:
            data[obj_field] = {}
        elif not isinstance(val, dict):
            raise ValidationError(f"Field '{obj_field}' must be object")

    for bool_field in ("beta", "experimental", "_disabled"):
        data.setdefault(bool_field, False)
        if not isinstance(data[bool_field], bool):
            raise ValidationError(f"Field '{bool_field}' must be boolean")

    if "ui" in data and data["ui"] is not None:
        data["ui"] = _validate_ui_block(data["ui"])
    else:
        data.pop("ui", None)

    if "cli" in data and data["cli"] is not None:
        data["cli"] = _validate_cli_block(data["cli"])
    else:
        data.pop("cli", None)

    if "skills" in data and data["skills"] is not None:
        data["skills"] = _validate_skills(data["skills"])
    else:
        data.pop("skills", None)

    return data
