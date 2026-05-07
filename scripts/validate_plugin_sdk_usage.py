from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


FORBIDDEN_RUNTIME_SURFACES = {
    "service_registry",
    "event_bus",
    "storage",
    "http",
    "operations",
    "state",
    "logger",
}

# `BasePlugin` (реэкспорт из core) исторически предоставляет `self.context.*`.
# Это мощная, но нестабильная поверхность: плагины начинают зависеть от core-internals.
# Для SDK v0 канонический путь — `runtime.api` и helper-методы BasePlugin (`register_service`,
# `publish_event`, `register_http_endpoint`, `register_operation_handler`, `storage_*`, etc).
FORBIDDEN_CONTEXT_SURFACES = {
    "services",
    "event_bus",
    "storage",
    "http",
    "operations",
    "state",
    "logger",
}

# Ещё жёстче: запрещаем любой доступ к самому `self.context` / `plugin.context` (не только к surface).
# Это убирает лазейки вида "ctx = self.context; ctx.http.register(...)".
FORBIDDEN_ANY_CONTEXT_ATTR = True

# Запрещаем прямой доступ к runtime API по методу (даже если runtime объект предоставляет api-методы).
# Канонический путь: методы BasePlugin (`call_service`, `storage_*`, `publish_event`, etc.)
# или `runtime.api.*` через эти методы.
FORBIDDEN_RUNTIME_API_METHODS = {
    "storage_get",
    "storage_set",
    "storage_delete",
    "storage_list_keys",
    "call_service",
    "has_service",
    "publish_event",
    "subscribe_event",
    "unsubscribe_event",
    "register_service",
    "register_http",
    "register_operation_handler",
    "publish_operation_ready",
}

# Максимально жёсткая гигиена: запрещаем ЛЮБОЙ доступ к runtime.* / self.runtime.* в plugins/.
# Даже если это не "метод API" — runtime остаётся core-internal объектом.
FORBIDDEN_ANY_RUNTIME_ATTR = True

# В репо есть legacy-плагин, который исторически использует `self.context.*`.
# Мы оставляем его временно, чтобы не ломать сборку/CI, но блокируем
# распространение этого паттерна на новые плагины.
#
# Важно: это allowlist по директории под `plugins/`.
ALLOWED_CONTEXT_USAGE_PLUGIN_DIRS: set[str] = set()

# Запрещаем импорт inspect в plugins/** — это почти всегда путь к frame-интроспекции.
FORBIDDEN_IMPORT_MODULES: set[str] = {"inspect"}


@dataclass(frozen=True)
class UsageViolation:
    path: str
    lineno: int
    statement: str
    surface: str


def _iter_python_files(plugins_dir: Path) -> Iterable[Path]:
    for p in sorted(plugins_dir.rglob("*.py")):
        rel = p.relative_to(plugins_dir).as_posix()
        parts = rel.split("/")

        # Exclude dedicated test plugins directory: plugins/test/**
        if parts and parts[0] == "test":
            continue

        # Exclude non-SDK plugin projects vendored under plugins/.
        # `client-manager-plugin` is a standalone agent-side service and is not constrained
        # by the in-process Plugin SDK surface rules.
        if parts and parts[0] == "client-manager-plugin":
            continue

        # Exclude any tests inside a plugin (e.g. plugins/foo/tests/**)
        if "tests" in parts:
            continue

        # Exclude standalone test modules inside a plugin (e.g. test_*.py, *_test.py)
        if p.name.startswith("test_") or p.name.endswith("_test.py"):
            continue

        yield p


def scan_plugins_forbidden_runtime_usage(root: Path) -> list[UsageViolation]:
    plugins_dir = root / "plugins"
    if not plugins_dir.exists():
        return []

    violations: list[UsageViolation] = []

    for path in _iter_python_files(plugins_dir):
        rel = path.relative_to(plugins_dir).as_posix()
        plugin_dir = rel.split("/", 1)[0] if rel else ""
        allow_context = plugin_dir in ALLOWED_CONTEXT_USAGE_PLUGIN_DIRS

        content = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(content, filename=str(path))
        except SyntaxError:
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

        def _is_forbidden_runtime_surface(node: ast.Attribute) -> str | None:
            if node.attr not in FORBIDDEN_RUNTIME_SURFACES:
                return None

            base = node.value
            # runtime.<surface>
            if isinstance(base, ast.Name) and base.id == "runtime":
                return node.attr
            # self.runtime.<surface> OR plugin.runtime.<surface>
            if isinstance(base, ast.Attribute) and base.attr == "runtime":
                return node.attr
            return None

        def _is_forbidden_runtime_api_method(node: ast.Attribute) -> str | None:
            if node.attr not in FORBIDDEN_RUNTIME_API_METHODS:
                return None
            base = node.value
            # runtime.<method>
            if isinstance(base, ast.Name) and base.id == "runtime":
                return node.attr
            # self.runtime.<method> OR plugin.runtime.<method>
            if isinstance(base, ast.Attribute) and base.attr == "runtime":
                return node.attr
            return None

        def _is_any_runtime_attr(node: ast.Attribute) -> str | None:
            if not FORBIDDEN_ANY_RUNTIME_ATTR:
                return None
            base = node.value
            # runtime.<anything>
            if isinstance(base, ast.Name) and base.id == "runtime":
                return node.attr
            # self.runtime.<anything> OR plugin.runtime.<anything>
            if isinstance(base, ast.Attribute) and base.attr == "runtime":
                return node.attr
            return None

        def _is_forbidden_context_surface(node: ast.Attribute) -> str | None:
            if allow_context:
                return None
            if node.attr not in FORBIDDEN_CONTEXT_SURFACES:
                return None

            base = node.value
            # self.context.<surface>
            if isinstance(base, ast.Attribute) and base.attr == "context":
                if isinstance(base.value, ast.Name) and base.value.id in {"self", "plugin"}:
                    return node.attr
            return None

        def _is_any_context_attr(node: ast.Attribute) -> bool:
            if allow_context:
                return False
            if not FORBIDDEN_ANY_CONTEXT_ATTR:
                return False
            # Allow: self.context.operation_context (and deeper chains).
            # Ban: direct reads of self.context / plugin.context.
            if node.attr == "context":
                parent = getattr(node, "parent", None)
                if isinstance(parent, ast.Attribute) and parent.attr == "operation_context":
                    return False
            # Allow the minimal safe surface for correlation/observability:
            # self.context.operation_context (and deeper chains) are OK.
            # We still ban all other direct `self.context` uses.
            if node.attr == "operation_context":
                base = node.value
                if (
                    isinstance(base, ast.Attribute)
                    and base.attr == "context"
                    and isinstance(base.value, ast.Name)
                    and base.value.id in {"self", "plugin"}
                ):
                    return False
            # self.context OR plugin.context
            if node.attr != "context":
                return False
            base = node.value
            return isinstance(base, ast.Name) and base.id in {"self", "plugin"}

        def _is_globals_locals_magic(target: ast.expr, key: str) -> bool:
            """
            Catch dynamic bypasses like globals()["runtime"] / locals()["context"].
            """
            if not isinstance(target, ast.Subscript):
                return False
            if not isinstance(target.value, ast.Call):
                return False
            call = target.value
            if not isinstance(call.func, ast.Name):
                return False
            if call.func.id not in {"globals", "locals"}:
                return False
            sl = target.slice
            if isinstance(sl, ast.Constant) and sl.value == key:
                return True
            return False

        def _is_vars_magic(target: ast.expr, key: str) -> bool:
            """
            Catch vars(self)["context"], vars(plugin)["context"], vars()["runtime"].
            """
            if not isinstance(target, ast.Subscript):
                return False
            if not isinstance(target.value, ast.Call):
                return False
            call = target.value
            if not (isinstance(call.func, ast.Name) and call.func.id == "vars"):
                return False
            sl = target.slice
            if not (isinstance(sl, ast.Constant) and sl.value == key):
                return False
            # vars() -> locals()
            if len(call.args) == 0:
                return True
            # vars(self) / vars(plugin)
            if len(call.args) == 1 and isinstance(call.args[0], ast.Name) and call.args[0].id in {
                "self",
                "plugin",
            }:
                return True
            return False

        def _is_dunder_dict_magic(target: ast.expr, key: str) -> bool:
            """
            Catch self.__dict__["context"] / plugin.__dict__["context"] and similar for runtime.
            """
            if not isinstance(target, ast.Subscript):
                return False
            sl = target.slice
            if not (isinstance(sl, ast.Constant) and sl.value == key):
                return False
            base = target.value
            if not isinstance(base, ast.Attribute):
                return False
            if base.attr != "__dict__":
                return False
            if not isinstance(base.value, ast.Name):
                return False
            return base.value.id in {"self", "plugin"}

        def _is_builtins_globals_magic(node: ast.Call) -> bool:
            """
            Catch getattr(__builtins__, "globals")()["runtime"] and similar.
            """
            if not isinstance(node.func, ast.Name) or node.func.id != "getattr":
                return False
            if len(node.args) < 2:
                return False
            base, attr = node.args[0], node.args[1]
            if not (isinstance(base, ast.Name) and base.id == "__builtins__"):
                return False
            if not (isinstance(attr, ast.Constant) and attr.value == "globals"):
                return False
            return True

        def _is_inspect_currentframe_f_locals(target: ast.Subscript, key: str) -> bool:
            """
            Catch inspect.currentframe().f_locals["context"] / ...["runtime"].
            """
            if not isinstance(target, ast.Subscript):
                return False
            sl = target.slice
            if not (isinstance(sl, ast.Constant) and sl.value == key):
                return False
            base = target.value
            # frame.f_locals["key"]
            if not isinstance(base, ast.Attribute):
                return False
            if base.attr != "f_locals":
                return False
            frame_obj = base.value
            # inspect.currentframe()
            if not isinstance(frame_obj, ast.Call):
                return False
            if not isinstance(frame_obj.func, ast.Attribute):
                return False
            if frame_obj.func.attr != "currentframe":
                return False
            mod = frame_obj.func.value
            if not isinstance(mod, ast.Name) or mod.id != "inspect":
                return False
            return True

        class _Visitor(ast.NodeVisitor):
            def __init__(self) -> None:
                self._in_type_checking = 0

            def generic_visit(self, node: ast.AST) -> None:
                # Attach parent links for small context-aware exceptions
                # (e.g. allow `self.context.operation_context` only).
                for child in ast.iter_child_nodes(node):
                    setattr(child, "parent", node)
                super().generic_visit(node)

            def visit_Import(self, node: ast.Import) -> None:
                if self._in_type_checking:
                    return
                for alias in node.names:
                    if alias.name in FORBIDDEN_IMPORT_MODULES:
                        lineno = getattr(node, "lineno", 1)
                        line = lines[lineno - 1] if 1 <= lineno <= len(lines) else ""
                        stmt = ast.get_source_segment(content, node) or line.strip()
                        violations.append(
                            UsageViolation(
                                path=str(path.relative_to(root)),
                                lineno=lineno,
                                statement=stmt.strip(),
                                surface=f"import {alias.name}",
                            )
                        )
                self.generic_visit(node)

            def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
                if self._in_type_checking:
                    return
                if node.module in FORBIDDEN_IMPORT_MODULES:
                    lineno = getattr(node, "lineno", 1)
                    line = lines[lineno - 1] if 1 <= lineno <= len(lines) else ""
                    stmt = ast.get_source_segment(content, node) or line.strip()
                    violations.append(
                        UsageViolation(
                            path=str(path.relative_to(root)),
                            lineno=lineno,
                            statement=stmt.strip(),
                            surface=f"from {node.module} import ...",
                        )
                    )
                self.generic_visit(node)

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

            def visit_Attribute(self, node: ast.Attribute) -> None:
                if self._in_type_checking:
                    return

                # Explicitly forbid frame attribute access even without inspect import
                # (e.g. someone could receive a frame object indirectly).
                if node.attr in {"f_locals", "f_globals"}:
                    lineno = getattr(node, "lineno", 1)
                    line = lines[lineno - 1] if 1 <= lineno <= len(lines) else ""
                    stmt = ast.get_source_segment(content, node) or line.strip()
                    violations.append(
                        UsageViolation(
                            path=str(path.relative_to(root)),
                            lineno=lineno,
                            statement=stmt.strip(),
                            surface=f"frame.{node.attr}",
                        )
                    )

                if _is_any_context_attr(node):
                    lineno = getattr(node, "lineno", 1)
                    line = lines[lineno - 1] if 1 <= lineno <= len(lines) else ""
                    stmt = ast.get_source_segment(content, node) or line.strip()
                    violations.append(
                        UsageViolation(
                            path=str(path.relative_to(root)),
                            lineno=lineno,
                            statement=stmt.strip(),
                            surface="context",
                        )
                    )

                surface = _is_forbidden_runtime_surface(node)
                if surface:
                    lineno = getattr(node, "lineno", 1)
                    line = lines[lineno - 1] if 1 <= lineno <= len(lines) else ""
                    stmt = ast.get_source_segment(content, node) or line.strip()
                    violations.append(
                        UsageViolation(
                            path=str(path.relative_to(root)),
                            lineno=lineno,
                            statement=stmt.strip(),
                            surface=surface,
                        )
                    )
                method = _is_forbidden_runtime_api_method(node)
                if method:
                    lineno = getattr(node, "lineno", 1)
                    line = lines[lineno - 1] if 1 <= lineno <= len(lines) else ""
                    stmt = ast.get_source_segment(content, node) or line.strip()
                    violations.append(
                        UsageViolation(
                            path=str(path.relative_to(root)),
                            lineno=lineno,
                            statement=stmt.strip(),
                            surface=f"runtime.{method}",
                        )
                    )
                any_attr = _is_any_runtime_attr(node)
                if any_attr:
                    lineno = getattr(node, "lineno", 1)
                    line = lines[lineno - 1] if 1 <= lineno <= len(lines) else ""
                    stmt = ast.get_source_segment(content, node) or line.strip()
                    violations.append(
                        UsageViolation(
                            path=str(path.relative_to(root)),
                            lineno=lineno,
                            statement=stmt.strip(),
                            surface=f"runtime.{any_attr}",
                        )
                    )
                surface = _is_forbidden_context_surface(node)
                if surface:
                    lineno = getattr(node, "lineno", 1)
                    line = lines[lineno - 1] if 1 <= lineno <= len(lines) else ""
                    stmt = ast.get_source_segment(content, node) or line.strip()
                    violations.append(
                        UsageViolation(
                            path=str(path.relative_to(root)),
                            lineno=lineno,
                            statement=stmt.strip(),
                            surface=f"context.{surface}",
                        )
                    )
                self.generic_visit(node)

            def visit_Call(self, node: ast.Call) -> None:
                if self._in_type_checking:
                    return
                # Catch getattr(runtime, ...) and getattr(self.runtime, ...)
                try:
                    # Catch getattr(__builtins__, "globals")() / getattr(__builtins__, "locals")()
                    # Пресекаем цепочку без data-flow: просто запрещаем вызов.
                    if isinstance(node.func, ast.Call):
                        inner_call = node.func
                        if (
                            isinstance(inner_call.func, ast.Name)
                            and inner_call.func.id == "getattr"
                            and len(inner_call.args) >= 2
                        ):
                            base = inner_call.args[0]
                            attr = inner_call.args[1]
                            if (
                                isinstance(base, ast.Name)
                                and base.id == "__builtins__"
                                and isinstance(attr, ast.Constant)
                                and attr.value in {"globals", "locals"}
                            ):
                                lineno = getattr(node, "lineno", 1)
                                line = (
                                    lines[lineno - 1]
                                    if 1 <= lineno <= len(lines)
                                    else ""
                                )
                                stmt = ast.get_source_segment(content, node) or line.strip()
                                violations.append(
                                    UsageViolation(
                                        path=str(path.relative_to(root)),
                                        lineno=lineno,
                                        statement=stmt.strip(),
                                        surface=f'__builtins__.{attr.value}()',
                                    )
                                )

                    # Catch inspect.currentframe()
                    if (
                        isinstance(node.func, ast.Attribute)
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "inspect"
                        and node.func.attr == "currentframe"
                    ):
                        lineno = getattr(node, "lineno", 1)
                        line = (
                            lines[lineno - 1]
                            if 1 <= lineno <= len(lines)
                            else ""
                        )
                        stmt = ast.get_source_segment(content, node) or line.strip()
                        violations.append(
                            UsageViolation(
                                path=str(path.relative_to(root)),
                                lineno=lineno,
                                statement=stmt.strip(),
                                surface="inspect.currentframe()",
                            )
                        )

                    if isinstance(node.func, ast.Name) and node.func.id == "getattr":
                        if node.args:
                            target = node.args[0]
                            is_runtime = isinstance(target, ast.Name) and target.id == "runtime"
                            is_self_runtime = (
                                isinstance(target, ast.Attribute) and target.attr == "runtime"
                            )
                            if is_runtime or is_self_runtime:
                                lineno = getattr(node, "lineno", 1)
                                line = lines[lineno - 1] if 1 <= lineno <= len(lines) else ""
                                stmt = ast.get_source_segment(content, node) or line.strip()
                                violations.append(
                                    UsageViolation(
                                        path=str(path.relative_to(root)),
                                        lineno=lineno,
                                        statement=stmt.strip(),
                                        surface="getattr(runtime, ...)",
                                    )
                                )
                            # getattr(self, "context") / getattr(plugin, "context")
                            if (
                                not allow_context
                                and FORBIDDEN_ANY_CONTEXT_ATTR
                                and isinstance(target, ast.Name)
                                and target.id in {"self", "plugin"}
                                and len(node.args) >= 2
                                and isinstance(node.args[1], ast.Constant)
                                and node.args[1].value == "context"
                            ):
                                lineno = getattr(node, "lineno", 1)
                                line = lines[lineno - 1] if 1 <= lineno <= len(lines) else ""
                                stmt = ast.get_source_segment(content, node) or line.strip()
                                violations.append(
                                    UsageViolation(
                                        path=str(path.relative_to(root)),
                                        lineno=lineno,
                                        statement=stmt.strip(),
                                        surface='getattr(self, "context")',
                                    )
                                )
                    # Catch object.__getattribute__(self, "context") / object.__getattribute__(self, "runtime")
                    if (
                        isinstance(node.func, ast.Attribute)
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "object"
                        and node.func.attr == "__getattribute__"
                        and len(node.args) >= 2
                        and isinstance(node.args[0], ast.Name)
                        and node.args[0].id in {"self", "plugin"}
                        and isinstance(node.args[1], ast.Constant)
                        and node.args[1].value in {"context", "runtime"}
                    ):
                        key = str(node.args[1].value)
                        lineno = getattr(node, "lineno", 1)
                        line = lines[lineno - 1] if 1 <= lineno <= len(lines) else ""
                        stmt = ast.get_source_segment(content, node) or line.strip()
                        violations.append(
                            UsageViolation(
                                path=str(path.relative_to(root)),
                                lineno=lineno,
                                statement=stmt.strip(),
                                surface=f'object.__getattribute__({key})',
                            )
                        )
                except Exception:
                    pass
                self.generic_visit(node)

            def visit_Subscript(self, node: ast.Subscript) -> None:
                if self._in_type_checking:
                    return
                # Catch globals()["runtime"] / locals()["runtime"]
                if _is_globals_locals_magic(node, "runtime"):
                    lineno = getattr(node, "lineno", 1)
                    line = lines[lineno - 1] if 1 <= lineno <= len(lines) else ""
                    stmt = ast.get_source_segment(content, node) or line.strip()
                    violations.append(
                        UsageViolation(
                            path=str(path.relative_to(root)),
                            lineno=lineno,
                            statement=stmt.strip(),
                            surface='globals()["runtime"]',
                        )
                    )
                # Catch globals()["context"] / locals()["context"]
                if not allow_context and _is_globals_locals_magic(node, "context"):
                    lineno = getattr(node, "lineno", 1)
                    line = lines[lineno - 1] if 1 <= lineno <= len(lines) else ""
                    stmt = ast.get_source_segment(content, node) or line.strip()
                    violations.append(
                        UsageViolation(
                            path=str(path.relative_to(root)),
                            lineno=lineno,
                            statement=stmt.strip(),
                            surface='globals()["context"]',
                        )
                    )
                # Catch vars(self)["context"] / vars(plugin)["context"] / vars()["runtime"]
                if _is_vars_magic(node, "runtime"):
                    lineno = getattr(node, "lineno", 1)
                    line = lines[lineno - 1] if 1 <= lineno <= len(lines) else ""
                    stmt = ast.get_source_segment(content, node) or line.strip()
                    violations.append(
                        UsageViolation(
                            path=str(path.relative_to(root)),
                            lineno=lineno,
                            statement=stmt.strip(),
                            surface='vars()["runtime"]',
                        )
                    )
                if not allow_context and _is_vars_magic(node, "context"):
                    lineno = getattr(node, "lineno", 1)
                    line = lines[lineno - 1] if 1 <= lineno <= len(lines) else ""
                    stmt = ast.get_source_segment(content, node) or line.strip()
                    violations.append(
                        UsageViolation(
                            path=str(path.relative_to(root)),
                            lineno=lineno,
                            statement=stmt.strip(),
                            surface='vars()["context"]',
                        )
                    )
                # Catch self.__dict__["context"] / plugin.__dict__["context"]
                if _is_dunder_dict_magic(node, "runtime"):
                    lineno = getattr(node, "lineno", 1)
                    line = lines[lineno - 1] if 1 <= lineno <= len(lines) else ""
                    stmt = ast.get_source_segment(content, node) or line.strip()
                    violations.append(
                        UsageViolation(
                            path=str(path.relative_to(root)),
                            lineno=lineno,
                            statement=stmt.strip(),
                            surface='__dict__["runtime"]',
                        )
                    )
                if not allow_context and _is_dunder_dict_magic(node, "context"):
                    lineno = getattr(node, "lineno", 1)
                    line = lines[lineno - 1] if 1 <= lineno <= len(lines) else ""
                    stmt = ast.get_source_segment(content, node) or line.strip()
                    violations.append(
                        UsageViolation(
                            path=str(path.relative_to(root)),
                            lineno=lineno,
                            statement=stmt.strip(),
                            surface='__dict__["context"]',
                        )
                    )
                # Catch getattr(__builtins__, "globals")()["runtime"]
                # We detect this on the Subscript to keep reporting consistent.
                if isinstance(node.value, ast.Call) and _is_builtins_globals_magic(node.value):
                    sl = node.slice
                    if isinstance(sl, ast.Constant) and sl.value == "runtime":
                        lineno = getattr(node, "lineno", 1)
                        line = lines[lineno - 1] if 1 <= lineno <= len(lines) else ""
                        stmt = ast.get_source_segment(content, node) or line.strip()
                        violations.append(
                            UsageViolation(
                                path=str(path.relative_to(root)),
                                lineno=lineno,
                                statement=stmt.strip(),
                                surface='__builtins__.globals()["runtime"]',
                            )
                        )
                # Catch inspect.currentframe().f_locals["context"] / ["runtime"]
                if _is_inspect_currentframe_f_locals(node, "runtime"):
                    lineno = getattr(node, "lineno", 1)
                    line = lines[lineno - 1] if 1 <= lineno <= len(lines) else ""
                    stmt = ast.get_source_segment(content, node) or line.strip()
                    violations.append(
                        UsageViolation(
                            path=str(path.relative_to(root)),
                            lineno=lineno,
                            statement=stmt.strip(),
                            surface='inspect.currentframe().f_locals["runtime"]',
                        )
                    )
                if not allow_context and _is_inspect_currentframe_f_locals(node, "context"):
                    lineno = getattr(node, "lineno", 1)
                    line = lines[lineno - 1] if 1 <= lineno <= len(lines) else ""
                    stmt = ast.get_source_segment(content, node) or line.strip()
                    violations.append(
                        UsageViolation(
                            path=str(path.relative_to(root)),
                            lineno=lineno,
                            statement=stmt.strip(),
                            surface='inspect.currentframe().f_locals["context"]',
                        )
                        )
                self.generic_visit(node)

        _Visitor().visit(tree)

    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate that plugins avoid legacy runtime.* and self.context.* surfaces "
            "(prefer sdk helpers / runtime.api)."
        )
    )
    parser.add_argument("--root", default=".", help="Repo root directory")
    parser.add_argument("--enforce", action="store_true", help="Exit with non-zero code on violations")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    violations = scan_plugins_forbidden_runtime_usage(root)
    if violations:
        msg = "Forbidden legacy surface usage detected in plugins/:\n" + "\n".join(
            f"- {v.path}:{v.lineno}: {v.surface}  ({v.statement})" for v in violations
        )
        print(msg)
        return 1 if args.enforce else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

