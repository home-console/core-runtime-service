from __future__ import annotations

from pathlib import Path

from scripts import validate_no_vendor_namespaces


def test_vendor_namespaces_do_not_leak_outside_plugins() -> None:
    root = Path(__file__).resolve().parents[2]
    assert validate_no_vendor_namespaces.main(["--root", str(root), "--enforce"]) == 0

