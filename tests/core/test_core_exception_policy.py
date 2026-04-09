from __future__ import annotations

import ast
import re
from pathlib import Path


def test_core_forbids_broad_exception_catches() -> None:
    root = Path(__file__).resolve().parents[1]
    core_dir = root / "core"

    # We intentionally forbid broad exception catches in core/.
    # - "except Exception" hides bugs and breaks diagnostics.
    # - bare "except:" is even worse (swallows BaseException).
    # - "except BaseException" catches system-exiting errors (KeyboardInterrupt/SystemExit/etc).
    forbidden_patterns: list[tuple[str, re.Pattern[str]]] = [
        ("except Exception", re.compile(r"(?m)^\s*except\s+Exception\s*:")),
        ("except BaseException", re.compile(r"(?m)^\s*except\s+BaseException\s*:")),
        ("except:", re.compile(r"(?m)^\s*except\s*:\s*$")),
    ]

    violations: list[str] = []
    for path in sorted(core_dir.rglob("*.py")):
        if any(part in {"__pycache__", ".git", ".venv", "venv", "node_modules"} for part in path.parts):
            continue
        content = path.read_text(encoding="utf-8")
        for label, pattern in forbidden_patterns:
            for match in pattern.finditer(content):
                line = content.count("\n", 0, match.start()) + 1
                violations.append(f"{path.relative_to(root)}:{line}: {label}")

    assert not violations, "Forbidden broad exception catches in core/:\n" + "\n".join(violations)


def test_core_cancelled_error_is_re_raised() -> None:
    root = Path(__file__).resolve().parents[1]
    core_dir = root / "core"

    def _is_cancelled_error(exc: ast.expr | None) -> bool:
        if exc is None:
            return False
        if isinstance(exc, ast.Name):
            return exc.id == "CancelledError"
        if isinstance(exc, ast.Attribute):
            return isinstance(exc.value, ast.Name) and exc.value.id == "asyncio" and exc.attr == "CancelledError"
        return False

    def _contains_raise(nodes: list[ast.stmt]) -> bool:
        for node in ast.walk(ast.Module(body=nodes, type_ignores=[])):
            if isinstance(node, ast.Raise):
                return True
        return False

    def _contains_exit(nodes: list[ast.stmt]) -> bool:
        for node in ast.walk(ast.Module(body=nodes, type_ignores=[])):
            if isinstance(node, (ast.Return, ast.Break, ast.Continue)):
                return True
        return False

    violations: list[str] = []
    for path in sorted(core_dir.rglob("*.py")):
        if any(part in {"__pycache__", ".git", ".venv", "venv", "node_modules"} for part in path.parts):
            continue
        content = path.read_text(encoding="utf-8")
        lines = content.splitlines()
        try:
            tree = ast.parse(content, filename=str(path))
        except SyntaxError:
            # Other tests cover syntax; don't hide CancelledError issues behind parse failures.
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            for handler in node.handlers:
                if not _is_cancelled_error(handler.type):
                    continue
                lineno = getattr(handler, "lineno", 1)
                # Allow a *very* explicit opt-out for shutdown paths where CancelledError
                # is expected (e.g. awaiting a task we just cancelled).
                if 1 <= lineno <= len(lines) and "allow_cancelled_suppress" in lines[lineno - 1]:
                    continue
                if not (_contains_raise(handler.body) or _contains_exit(handler.body)):
                    violations.append(
                        f"{path.relative_to(root)}:{lineno}: except CancelledError must re-raise"
                    )

    assert not violations, "CancelledError must be re-raised in core/:\n" + "\n".join(violations)
