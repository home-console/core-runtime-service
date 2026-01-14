import pytest
from types import SimpleNamespace
from modules.api.auth import middleware
from modules.api.auth import jwt_tokens as jwt
from modules.api.auth.constants import AUTH_USERS_NAMESPACE


class MockRequest:
    def __init__(self, headers, runtime, path="/api/resource", cookies=None):
        self.headers = headers
        self.cookies = cookies or {}
        self.client = SimpleNamespace(host="127.0.0.1")
        self.url = SimpleNamespace(path=path)
        self.app = SimpleNamespace(state=SimpleNamespace(runtime=runtime))
        self.state = SimpleNamespace()


@pytest.mark.asyncio
async def test_require_auth_middleware_with_jwt(runtime):
    # Prepare user and token
    await runtime.storage.set(AUTH_USERS_NAMESPACE, "mwuser", {"scopes": ["read"], "is_admin": False})
    secret = await jwt.get_or_create_jwt_secret(runtime)
    token = jwt.generate_access_token("mwuser", ["read"], False, secret, expiration_seconds=60)

    req = MockRequest({"Authorization": f"Bearer {token}", "user-agent": "pytest"}, runtime)

    async def call_next(request):
        return SimpleNamespace(status_code=200)

    response = await middleware.require_auth_middleware(req, call_next)
    assert response.status_code == 200
    assert getattr(req.state, "auth_context", None) is not None
    assert getattr(req.state.auth_context, "user_id", None) == "mwuser"


@pytest.mark.asyncio
async def test_require_auth_middleware_without_credentials(runtime):
    req = MockRequest({}, runtime)

    async def call_next(request):
        return SimpleNamespace(status_code=200)

    response = await middleware.require_auth_middleware(req, call_next)
    assert response.status_code == 200
    assert getattr(req.state, "auth_context", None) is None
