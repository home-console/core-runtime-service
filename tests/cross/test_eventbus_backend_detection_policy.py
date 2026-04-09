from __future__ import annotations

import re
from pathlib import Path


def test_eventbus_forbids_string_backend_detection() -> None:
    """
    C6 guard: EventBus backend detection must not rely on adapter name substrings
    like '"sqlite" in adapter_name'.
    """
    root = Path(__file__).resolve().parents[1]
    core_dir = root / "core"

    # Keep this scoped to messaging-related files to avoid false positives elsewhere.
    targets = [
        core_dir / "messaging.py",
        core_dir / "messaging_storage.py",
        core_dir / "messaging_claim_manager.py",
    ]

    patterns = [
        re.compile(r"\"sqlite\"\s+in\s+"),
        re.compile(r"\"postgres\"\s+in\s+"),
        re.compile(r"\"postgresql\"\s+in\s+"),
    ]

    violations: list[str] = []
    for path in targets:
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8")
        for pattern in patterns:
            for match in pattern.finditer(content):
                line = content.count("\n", 0, match.start()) + 1
                violations.append(f"{path.relative_to(root)}:{line}: {match.group(0)!r}")

    assert not violations, "String-based backend detection found:\n" + "\n".join(violations)

