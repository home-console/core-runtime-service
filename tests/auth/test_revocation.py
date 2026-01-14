import importlib


def test_revocation_exports():
    rev = importlib.import_module("modules.api.auth.revocation")
    # Common revocation entrypoints
    assert any(hasattr(rev, name) for name in ("revoke_api_key", "revoke_session", "revoke_token"))
