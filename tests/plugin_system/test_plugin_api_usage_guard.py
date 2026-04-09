from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGINS_DIR = ROOT / "plugins"
BANNED_RUNTIME_ATTRS = {"service_registry", "event_bus", "storage", "http", "operations"}


def _is_base_plugin_file(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return False
    return "(BasePlugin)" in text


def _find_banned_runtime_accesses(path: Path) -> list[tuple[int, int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    issues: list[tuple[int, int, str]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        if node.attr not in BANNED_RUNTIME_ATTRS:
            continue

        parent = node.value
        if (
            isinstance(parent, ast.Attribute)
            and parent.attr == "runtime"
            and isinstance(parent.value, ast.Name)
            and parent.value.id == "self"
        ):
            issues.append((node.lineno, node.col_offset, node.attr))

    return issues


def test_base_plugins_do_not_access_runtime_internals_directly() -> None:
    """
    BasePlugin descendants must use plugin helpers/runtime.api instead of direct runtime internals.
    """
    violations: list[str] = []

    for path in sorted(PLUGINS_DIR.rglob("*.py")):
        if not _is_base_plugin_file(path):
            continue
        issues = _find_banned_runtime_accesses(path)
        for line, col, attr in issues:
            rel = path.relative_to(ROOT)
            violations.append(f"{rel}:{line}:{col} -> self.runtime.{attr}")

    assert not violations, "Direct runtime access in BasePlugin files:\n" + "\n".join(violations)

