"""
Architecture dependency report for the core/modules/plugins split.

The script is intentionally conservative:
- it reports runtime imports from ``core`` into ``modules``;
- it reports runtime imports from ``core`` into ``app``;
- it reports runtime imports from ``modules`` into ``plugins``;
- it reports runtime imports from ``modules`` into legacy ``core`` domains
    (``core.agent``, ``core.credentials``).

Imports inside ``if TYPE_CHECKING:`` blocks are ignored.

By default the script prints a report and exits with code 0. Pass
``--enforce`` to fail the process when violations are found.
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator


@dataclass(frozen=True)
class ImportViolation:
    source: str
    target: str
    module: str
    line: int
    kind: str


@dataclass
class ArchitectureReport:
    core_to_modules: list[ImportViolation] = field(default_factory=list)
    core_to_app: list[ImportViolation] = field(default_factory=list)
    modules_to_plugins: list[ImportViolation] = field(default_factory=list)
    plugins_to_modules: list[ImportViolation] = field(default_factory=list)
    modules_to_legacy_core: list[ImportViolation] = field(default_factory=list)

    def has_violations(self) -> bool:
        return bool(
            self.core_to_modules
            or self.core_to_app
            or self.modules_to_plugins
            or self.plugins_to_modules
            or self.modules_to_legacy_core
        )

    def summary(self) -> dict[str, int]:
        legacy_count = len(self.modules_to_legacy_core)
        return {
            "core_to_modules": len(self.core_to_modules),
            "core_to_app": len(self.core_to_app),
            "modules_to_plugins": len(self.modules_to_plugins),
            "plugins_to_modules": len(self.plugins_to_modules),
            "modules_to_legacy_core": legacy_count,
            "total": len(self.core_to_modules)
            + len(self.core_to_app)
            + len(self.modules_to_plugins)
            + len(self.plugins_to_modules)
            + legacy_count,
        }


def _is_type_checking_test(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "TYPE_CHECKING"
    if isinstance(node, ast.Attribute):
        return node.attr == "TYPE_CHECKING"
    return False


def _iter_files(root: Path) -> Iterator[Path]:
    for path in root.rglob("*.py"):
        if any(
            part in {"__pycache__", ".git", ".venv", "venv", "node_modules"}
            for part in path.parts
        ):
            continue
        yield path


def _classify_target(module_name: str | None) -> str | None:
    if not module_name:
        return None
    if module_name.startswith("modules"):
        return "modules"
    if module_name.startswith("app"):
        return "app"
    if module_name.startswith("plugins"):
        return "plugins"
    if module_name.startswith("core.agent") or module_name.startswith(
        "core.credentials"
    ):
        return "legacy_core_domain"
    return None


def _module_name_from_path(root: Path, path: Path) -> str:
    rel = path.relative_to(root).with_suffix("")
    return ".".join(rel.parts)


class _ImportCollector:
    def __init__(self, file_path: Path, root: Path):
        self.file_path = file_path
        self.root = root
        self.imports: list[ImportViolation] = []

    def collect(self) -> list[ImportViolation]:
        module_name = _module_name_from_path(self.root, self.file_path)
        try:
            tree = ast.parse(
                self.file_path.read_text(encoding="utf-8"), filename=str(self.file_path)
            )
        except SyntaxError as e:
            raise SyntaxError(
                f"Failed to parse {self.file_path}. "
                "This repo targets Python 3.13+. "
                "If you are running on macOS system Python (3.9), switch to Python 3.13+. "
                f"Original error: {e}"
            ) from e
        self._visit(tree, module_name, in_type_checking=False)
        return self.imports

    def _visit(
        self, node: ast.AST, module_name: str, *, in_type_checking: bool
    ) -> None:
        if isinstance(node, ast.If):
            is_type_checking = _is_type_checking_test(node.test)
            for child in node.body:
                self._visit(
                    child,
                    module_name,
                    in_type_checking=in_type_checking or is_type_checking,
                )
            for child in node.orelse:
                self._visit(child, module_name, in_type_checking=in_type_checking)
            return

        if isinstance(node, ast.Import):
            for alias in node.names:
                self._maybe_record(
                    module_name, alias.name, node.lineno, in_type_checking
                )
            return

        if isinstance(node, ast.ImportFrom):
            self._maybe_record(module_name, node.module, node.lineno, in_type_checking)
            return

        for child in ast.iter_child_nodes(node):
            self._visit(child, module_name, in_type_checking=in_type_checking)

    def _maybe_record(
        self,
        source_module: str,
        target_module: str | None,
        line: int,
        in_type_checking: bool,
    ) -> None:
        target_kind = _classify_target(target_module)
        if target_kind is None or in_type_checking:
            return

        source_kind = source_module.split(".", 1)[0]
        if source_kind == "core" and target_kind == "modules":
            self.imports.append(
                ImportViolation(
                    source=source_module,
                    target=target_module or "",
                    module=target_module or "",
                    line=line,
                    kind="core_to_modules",
                )
            )
        elif source_kind == "core" and target_kind == "app":
            self.imports.append(
                ImportViolation(
                    source=source_module,
                    target=target_module or "",
                    module=target_module or "",
                    line=line,
                    kind="core_to_app",
                )
            )
        elif source_kind == "modules" and target_kind == "plugins":
            self.imports.append(
                ImportViolation(
                    source=source_module,
                    target=target_module or "",
                    module=target_module or "",
                    line=line,
                    kind="modules_to_plugins",
                )
            )
        elif source_kind == "plugins" and target_kind == "modules":
            self.imports.append(
                ImportViolation(
                    source=source_module,
                    target=target_module or "",
                    module=target_module or "",
                    line=line,
                    kind="plugins_to_modules",
                )
            )
        elif source_kind == "modules" and target_kind == "legacy_core_domain":
            self.imports.append(
                ImportViolation(
                    source=source_module,
                    target=target_module or "",
                    module=target_module or "",
                    line=line,
                    kind="modules_to_legacy_core",
                )
            )


def scan_architecture(root: Path) -> ArchitectureReport:
    report = ArchitectureReport()
    for path in _iter_files(root):
        module_name = _module_name_from_path(root, path)
        if not (
            module_name.startswith("core")
            or module_name.startswith("modules")
            or module_name.startswith("plugins")
        ):
            continue

        try:
            collector = _ImportCollector(path, root)
            for violation in collector.collect():
                if violation.kind == "core_to_modules":
                    report.core_to_modules.append(violation)
                elif violation.kind == "core_to_app":
                    report.core_to_app.append(violation)
                elif violation.kind == "modules_to_plugins":
                    report.modules_to_plugins.append(violation)
                elif violation.kind == "plugins_to_modules":
                    report.plugins_to_modules.append(violation)
                elif violation.kind == "modules_to_legacy_core":
                    report.modules_to_legacy_core.append(violation)
        except SyntaxError as exc:
            raise SyntaxError(f"Failed to parse {path}: {exc}") from exc

    return report


def _print_section(title: str, violations: Iterable[ImportViolation]) -> None:
    violations = list(violations)
    print(f"\n{title}: {len(violations)}")
    if not violations:
        print("  OK")
        return

    for violation in violations:
        print(f"  - {violation.source}:{violation.line} -> {violation.target}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Report architecture import-rule violations."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root to scan",
    )
    parser.add_argument(
        "--enforce",
        action="store_true",
        help="Exit with non-zero status if violations are found",
    )
    args = parser.parse_args(argv)

    report = scan_architecture(args.root)
    summary = report.summary()

    print("Architecture dependency report")
    print(f"Root: {args.root}")
    print(f"Total violations: {summary['total']}")
    print(f"  core -> modules runtime imports: {summary['core_to_modules']}")
    print(f"  core -> app runtime imports: {summary['core_to_app']}")
    print(f"  modules -> plugins runtime imports: {summary['modules_to_plugins']}")
    print(f"  plugins -> modules runtime imports: {summary['plugins_to_modules']}")
    print(
        f"  modules -> legacy core domain imports: {summary['modules_to_legacy_core']}"
    )

    _print_section("core -> modules", report.core_to_modules)
    _print_section("core -> app", report.core_to_app)
    _print_section("modules -> plugins", report.modules_to_plugins)
    _print_section("plugins -> modules", report.plugins_to_modules)
    _print_section("modules -> legacy core domain", report.modules_to_legacy_core)

    if args.enforce and report.has_violations():
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
