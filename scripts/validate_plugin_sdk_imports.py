from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


FORBIDDEN_TOPLEVEL = {"core", "modules", "app"}


@dataclass(frozen=True)
class ImportViolation:
    path: str
    lineno: int
    statement: str
    target: str


def _iter_python_files(plugins_dir: Path) -> Iterable[Path]:
    for p in sorted(plugins_dir.rglob("*.py")):
        rel = p.relative_to(plugins_dir).as_posix()
        parts = rel.split("/")

        # Exclude dedicated test plugins directory: plugins/test/**
        if parts and parts[0] == "test":
            continue

        # Exclude any tests inside a plugin (e.g. plugins/foo/tests/**)
        if "tests" in parts:
            continue

        # Exclude standalone test modules inside a plugin (e.g. test_*.py, *_test.py)
        if p.name.startswith("test_") or p.name.endswith("_test.py"):
            continue
        yield p


def _plugin_root_for(path: Path, plugins_dir: Path) -> Path | None:
    try:
        rel = path.relative_to(plugins_dir)
    except ValueError:
        return None
    parts = rel.parts
    if not parts:
        return None
    # Ignore plugins/__init__.py and other files directly under plugins/
    if len(parts) == 1 and parts[0].endswith(".py"):
        return None
    return plugins_dir / parts[0]


def _local_toplevel_modules(plugin_root: Path) -> set[str]:
    """
    Возвращает имена top-level модулей, которые *локально* существуют у плагина.

    Это важно, потому что некоторые плагины (например client-manager-plugin) имеют
    свой пакет `app/` и импортируют `app.*` как внутренности плагина, а не project-level `app/`.
    """
    names: set[str] = set()
    if not plugin_root.exists():
        return names
    for child in plugin_root.iterdir():
        if child.name.startswith("."):
            continue
        if child.is_dir():
            if (child / "__init__.py").exists():
                names.add(child.name)
        elif child.is_file() and child.suffix == ".py":
            names.add(child.stem)
    return names


def _extract_import_targets(node: ast.AST) -> list[str]:
    targets: list[str] = []
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.name:
                targets.append(alias.name)
    elif isinstance(node, ast.ImportFrom):
        if node.level and node.level > 0:
            return []
        if node.module:
            targets.append(node.module)
    return targets


def scan_plugins_forbidden_imports(root: Path) -> list[ImportViolation]:
    plugins_dir = root / "plugins"
    if not plugins_dir.exists():
        return []

    violations: list[ImportViolation] = []
    local_cache: dict[Path, set[str]] = {}

    for path in _iter_python_files(plugins_dir):
        plugin_root = _plugin_root_for(path, plugins_dir)
        if plugin_root is None:
            continue
        if plugin_root not in local_cache:
            local_cache[plugin_root] = _local_toplevel_modules(plugin_root)
        local_toplevel = local_cache[plugin_root]

        content = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(content, filename=str(path))
        except SyntaxError:
            # If plugin file cannot be parsed, this should be handled elsewhere; don't mask it here.
            continue

        lines = content.splitlines()

        def _is_type_checking_test(test: ast.expr) -> bool:
            # if TYPE_CHECKING:
            if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
                return True
            # if typing.TYPE_CHECKING:
            if isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING":
                return True
            return False

        class _Visitor(ast.NodeVisitor):
            def __init__(self) -> None:
                self._in_type_checking = 0

            def visit_If(self, node: ast.If) -> None:
                if _is_type_checking_test(node.test):
                    self._in_type_checking += 1
                    for stmt in node.body:
                        self.visit(stmt)
                    self._in_type_checking -= 1
                    for stmt in node.orelse:
                        self.visit(stmt)
                    return
                self.generic_visit(node)

            def visit_Import(self, node: ast.Import) -> None:
                if self._in_type_checking:
                    return
                self._check(node)

            def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
                if self._in_type_checking:
                    return
                self._check(node)

            def _check(self, node: ast.AST) -> None:
                lineno = getattr(node, "lineno", 1)
                line = lines[lineno - 1] if 1 <= lineno <= len(lines) else ""
                for target in _extract_import_targets(node):
                    top = target.split(".", 1)[0]
                    if top not in FORBIDDEN_TOPLEVEL:
                        continue
                    if top in local_toplevel:
                        continue
                    stmt = ast.get_source_segment(content, node) or line.strip()
                    violations.append(
                        ImportViolation(
                            path=str(path.relative_to(root)),
                            lineno=lineno,
                            statement=stmt.strip(),
                            target=target,
                        )
                    )

        _Visitor().visit(tree)

    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate that plugins import only sdk (no core/modules/app).")
    parser.add_argument("--root", default=".", help="Repo root directory")
    parser.add_argument("--enforce", action="store_true", help="Exit with non-zero code on violations")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    violations = scan_plugins_forbidden_imports(root)
    if violations:
        msg = "Forbidden imports detected in plugins/:\n" + "\n".join(
            f"- {v.path}:{v.lineno}: {v.target}  ({v.statement})" for v in violations
        )
        print(msg)
        return 1 if args.enforce else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

