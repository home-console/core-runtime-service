"""Domain-типы не зависят от modules/security или modules/credentials."""

import ast
from pathlib import Path


def get_imports(filepath: Path) -> list[str]:
    tree = ast.parse(filepath.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports


def test_domain_has_no_security_imports():
    domain_dir = Path("modules/domain")
    for py_file in domain_dir.glob("*.py"):
        imports = get_imports(py_file)
        for imp in imports:
            assert not imp.startswith("modules.security"), (
                f"{py_file.name} imports from modules.security: {imp}. "
                f"Domain must not depend on security."
            )
            assert not imp.startswith("modules.credentials"), (
                f"{py_file.name} imports from modules.credentials: {imp}. "
                f"Domain must not depend on credentials."
            )


def test_domain_types_importable():
    from modules.domain import (
        CredentialAccessDenied,
        CredentialAccessLevel,
        CredentialPolicy,
        RiskAction,
        Role,
        TrustAction,
        TrustLevel,
    )

    assert TrustLevel.NORMAL == "normal"
    assert RiskAction.ALLOW == "allow"
    assert Role.ADMIN == "admin"
    assert CredentialAccessLevel.READ_SECRET.value == "read_secret"
    assert isinstance(CredentialPolicy.__name__, str)
    assert TrustAction.ALLOW.value == "allow"
    assert isinstance(CredentialAccessDenied("cred-1"), Exception)


def test_backward_compatibility_security_imports():
    """Старые импорты из modules.security продолжают работать."""
    from modules.security import TrustLevel
    from modules.security.rbac_models import Role, CredentialPolicy
    from modules.security.risk.models import RiskAction

    assert TrustLevel.NORMAL == "normal"
    assert RiskAction.ALLOW == "allow"
    assert Role.ADMIN == "admin"
    assert isinstance(CredentialPolicy.__name__, str)

