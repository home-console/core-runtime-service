import importlib


def test_middleware_exports():
    mw = importlib.import_module("modules.api.auth.middleware")
    # Common export names: require_auth_middleware, auth_middleware
    assert any(hasattr(mw, name) for name in ("require_auth_middleware", "auth_middleware"))
