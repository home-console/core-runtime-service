from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path


VENDOR_NAMESPACE_PATTERNS: dict[str, re.Pattern[str]] = {
    # Matches yandex namespace as a word or namespace prefix, but does NOT match oauth_yandex plugin ids.
    "yandex": re.compile(
        r"(?:(?<![A-Za-z0-9_])yandex(?![A-Za-z0-9_])|yandex[.:])"
    ),
}


ALLOWED_SUBSTRINGS: tuple[str, ...] = (
    # Plugin identifiers / URLs are allowed to mention vendor name.
    "oauth_yandex",
    "oauth-yandex",
)

ALLOWED_PATH_SUFFIXES: tuple[str, ...] = (
    # The validator itself contains vendor patterns by design.
    "scripts/validate_no_vendor_namespaces.py",
    # Policy/docs may mention vendor namespaces as examples.
    "docs/CORE_KERNEL_POLICY_RU.md",
)


@dataclass(frozen=True)
class Violation:
    path: str
    namespace: str
    line_no: int
    line: str


def _iter_text_files(root: Path) -> list[Path]:
    exts = {".py", ".md", ".yaml", ".yml", ".sh"}
    out: list[Path] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() not in exts:
            continue
        out.append(p)
    return out


def scan(root: Path) -> list[Violation]:
    violations: list[Violation] = []
    plugins_dir = root / "plugins"

    scan_roots = [
        root / "core",
        root / "modules",
        root / "tests",
        root / "scripts",
        root / "docs",
    ]

    for base in scan_roots:
        if not base.exists():
            continue
        for path in _iter_text_files(base):
            # Allow vendor namespaces inside plugins only.
            try:
                if plugins_dir in path.parents:
                    continue
            except Exception:
                pass

            rel_posix = path.relative_to(root).as_posix()
            if rel_posix.endswith(ALLOWED_PATH_SUFFIXES):
                continue

            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            for i, line in enumerate(content.splitlines(), start=1):
                if any(s in line for s in ALLOWED_SUBSTRINGS):
                    continue
                for ns, pat in VENDOR_NAMESPACE_PATTERNS.items():
                    if pat.search(line):
                        violations.append(
                            Violation(
                                path=str(path),
                                namespace=ns,
                                line_no=i,
                                line=line.strip(),
                            )
                        )
    return violations


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="repo root (core-runtime-service)")
    ap.add_argument("--enforce", action="store_true", help="exit 1 if violations found")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    violations = scan(root)
    if not violations:
        return 0

    for v in violations[:200]:
        print(f"[vendor-namespace] {v.namespace}: {v.path}:{v.line_no}: {v.line}")
    if len(violations) > 200:
        print(f"... and {len(violations) - 200} more")

    return 1 if args.enforce else 0


if __name__ == "__main__":
    raise SystemExit(main())

