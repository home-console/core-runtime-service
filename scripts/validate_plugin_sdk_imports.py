#!/usr/bin/env python3
"""
Plugin SDK import guard (AST-based).

Goal: plugins must not import internal runtime layers directly.

Validates Python files under plugins/**.py and fails if any file imports:
  - core
  - modules
  - app
  - plugins

By default plugins/test/** is excluded (can be enabled via --include-tests).
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


BANNED_TOP_LEVEL_IMPORTS: set[str] = {"core", "modules", "app", "plugins"}


@dataclass(frozen=True)
class ImportViolation:
    path: Path
    line: int
    col: int
    imported: str
    statement: str


def _iter_plugin_py_files(root: Path, *, include_tests: bool) -> Iterable[Path]:
    plugins_dir = root / "plugins"
    if not plugins_dir.exists():
        return []

    for p in plugins_dir.rglob("*.py"):
        rel = p.relative_to(root)
        if not include_tests:
            # Dedicated test plugins
            if rel.parts[:2] == ("plugins", "test"):
                continue
            # Per-plugin test packages (plugins/foo/tests/**)
            if len(rel.parts) >= 3 and rel.parts[0] == "plugins" and rel.parts[2] == "tests":
                continue
            # Standalone test modules inside plugin trees
            if p.name.startswith("test_") or p.name.endswith("_test.py"):
                continue
        yield p


def _top_level_name(module: str | None) -> str | None:
    if not module:
        return None
    return module.split(".", 1)[0]


def _format_import_stmt(node: ast.AST) -> str:
    try:
        if isinstance(node, ast.Import):
            names = ", ".join(n.name for n in node.names)
            return f"import {names}"
        if isinstance(node, ast.ImportFrom):
            dots = "." * node.level
            mod = node.module or ""
            names = ", ".join(n.name for n in node.names)
            return f"from {dots}{mod} import {names}"
    except Exception:
        pass
    return node.__class__.__name__


def _find_violations_in_file(path: Path, *, root: Path) -> list[ImportViolation]:
    try:
        src = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        src = path.read_text(encoding="utf-8", errors="replace")

    rel = path.relative_to(root)

    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError as e:
        return [
            ImportViolation(
                path=rel,
                line=getattr(e, "lineno", 1) or 1,
                col=getattr(e, "offset", 0) or 0,
                imported="(syntax error)",
                statement=str(e).strip(),
            )
        ]

    violations: list[ImportViolation] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = _top_level_name(alias.name)
                if top in BANNED_TOP_LEVEL_IMPORTS:
                    violations.append(
                        ImportViolation(
                            path=rel,
                            line=node.lineno,
                            col=node.col_offset,
                            imported=alias.name,
                            statement=_format_import_stmt(node),
                        )
                    )
        elif isinstance(node, ast.ImportFrom):
            # relative imports inside plugins are OK; we only block absolute banned roots
            if node.level and node.level > 0:
                continue
            top = _top_level_name(node.module)
            if top in BANNED_TOP_LEVEL_IMPORTS:
                violations.append(
                    ImportViolation(
                        path=rel,
                        line=node.lineno,
                        col=node.col_offset,
                        imported=node.module or top or "",
                        statement=_format_import_stmt(node),
                    )
                )

    return violations


def _print_report(violations: Sequence[ImportViolation]) -> None:
    if not violations:
        print("OK: no forbidden imports detected in plugins.")
        return

    print("FAIL: detected forbidden imports in plugins/*")
    print()

    by_file: dict[Path, list[ImportViolation]] = {}
    for v in violations:
        by_file.setdefault(v.path, []).append(v)

    for path in sorted(by_file.keys()):
        print(f"- {path}")
        for v in sorted(by_file[path], key=lambda x: (x.line, x.col, x.imported)):
            print(f"  - {v.line}:{v.col}  {v.statement}")
        print()

    print("Banned top-level imports:", ", ".join(sorted(BANNED_TOP_LEVEL_IMPORTS)))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Plugin SDK import rules (AST-based).")
    parser.add_argument(
        "--root",
        default=".",
        help="Path to core-runtime-service root (defaults to current directory).",
    )
    # Backward-compatible flag: older callers/tests pass --enforce.
    # This guard always enforces; the flag is a no-op.
    parser.add_argument(
        "--enforce",
        action="store_true",
        help="(deprecated/no-op) Guard is always enforced; kept for compatibility.",
    )
    parser.add_argument(
        "--include-tests",
        action="store_true",
        help="Also validate plugins/test/** (excluded by default).",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    root = Path(args.root).resolve()
    violations: list[ImportViolation] = []
    for p in _iter_plugin_py_files(root, include_tests=bool(args.include_tests)):
        violations.extend(_find_violations_in_file(p, root=root))

    _print_report(violations)
    return 0 if not violations else 1


if __name__ == "__main__":
    raise SystemExit(main())

