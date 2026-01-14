import importlib


def test_jwt_module_exports():
    jwt = importlib.import_module("modules.api.auth.jwt_tokens")
    assert hasattr(jwt, "generate_access_token") or hasattr(jwt, "create_access_token")
    # Ensure at least one common function is callable
    func = getattr(jwt, "generate_access_token", None) or getattr(jwt, "create_access_token", None)
    assert callable(func)
