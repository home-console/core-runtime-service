"""
Tests for modules/api/auth/middleware.py (coverage: 48% → 70%+)
"""
import pytest
import time
import secrets
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from modules.api.auth.middleware import require_auth_middleware, get_request_context
from modules.api.auth.context import RequestContext
from modules.api.auth.constants import AUTH_USERS_NAMESPACE, AUTH_SESSIONS_NAMESPACE


class FakeStorage:
    def __init__(self):
        self._d = {}

    async def get(self, ns, key):
        return self._d.get(ns, {}).get(key)

    async def set(self, ns, key, value):
        self._d.setdefault(ns, {})[key] = value

    async def delete(self, ns, key):
        self._d.get(ns, {}).pop(key, None)


class FakeServiceRegistry:
    async def call(self, *args, **kwargs):
        return None


def make_runtime(storage=None):
    rt = SimpleNamespace(
        storage=storage or FakeStorage(),
        service_registry=FakeServiceRegistry(),
    )
    app_state = SimpleNamespace(runtime=rt)
    return rt, app_state


def make_request(method="GET", path="/api/test", headers=None, cookies=None, runtime=None):
    """Construct a mock FastAPI Request with app.state.runtime populated."""
    req = MagicMock()
    req.method = method
    req.url = SimpleNamespace(path=path)
    req.headers = dict(headers or {})
    req.cookies = dict(cookies or {})
    req.client = SimpleNamespace(host="127.0.0.1")
    req.scope = {"method": method}

    if runtime:
        req.app = SimpleNamespace(state=SimpleNamespace(runtime=runtime))
    else:
        req.app = SimpleNamespace(state=SimpleNamespace(runtime=None))

    req.state = SimpleNamespace()
    return req


async def _call_next(request):
    return MagicMock(status_code=200)


def make_context(user_id="u1", scopes=None, is_admin=False, source="jwt"):
    return RequestContext(
        subject=f"user:{user_id}",
        scopes=set(scopes or ["devices.read"]),
        is_admin=is_admin,
        source=source,
        user_id=user_id,
        session_id=None,
    )


# ---------------------------------------------------------------------------
# get_request_context
# ---------------------------------------------------------------------------

class TestGetRequestContext:

    @pytest.mark.asyncio
    async def test_returns_none_when_not_set(self):
        req = MagicMock()
        req.state = SimpleNamespace()
        result = await get_request_context(req)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_context_when_set(self):
        ctx = make_context()
        req = MagicMock()
        req.state = SimpleNamespace(auth_context=ctx)
        result = await get_request_context(req)
        assert result is ctx


# ---------------------------------------------------------------------------
# require_auth_middleware
# ---------------------------------------------------------------------------

class TestOptionsPassthrough:

    @pytest.mark.asyncio
    async def test_options_request_skips_auth(self):
        """OPTIONS should immediately call_next without any auth."""
        req = make_request(method="OPTIONS")
        called = []

        async def cn(r):
            called.append(True)
            return MagicMock(status_code=200)

        await require_auth_middleware(req, cn)
        assert called, "call_next was not called for OPTIONS"


class TestJwtAuth:

    @pytest.mark.asyncio
    async def test_valid_jwt_sets_context(self):
        rt, app_state = make_runtime()
        req = make_request(
            method="GET",
            path="/api/data",
            headers={"authorization": "Bearer header.payload.sig"},
            runtime=rt,
        )
        ctx = make_context()

        async def cn(r):
            return MagicMock(status_code=200)

        with patch("modules.api.auth.middleware.extract_jwt_from_header", return_value="header.payload.sig"):
            with patch("modules.api.auth.middleware.validate_jwt_token", AsyncMock(return_value=ctx)):
                await require_auth_middleware(req, cn)

        assert req.state.auth_context is ctx

    @pytest.mark.asyncio
    async def test_invalid_jwt_falls_through_to_none_context(self):
        rt, _ = make_runtime()
        req = make_request(
            method="GET",
            path="/api/data",
            headers={"authorization": "Bearer bad.jwt.token"},
            runtime=rt,
        )

        async def cn(r):
            return MagicMock(status_code=200)

        with patch("modules.api.auth.middleware.extract_jwt_from_header", return_value="bad.tok"):
            with patch("modules.api.auth.middleware.validate_jwt_token", AsyncMock(return_value=None)):
                await require_auth_middleware(req, cn)

        # Context should be None since JWT validation failed
        assert getattr(req.state, "auth_context", None) is None

    @pytest.mark.asyncio
    async def test_jwt_exception_falls_through(self):
        rt, _ = make_runtime()
        req = make_request(
            method="GET",
            path="/api/data",
            headers={"authorization": "Bearer x.y.z"},
            runtime=rt,
        )

        async def cn(r):
            return MagicMock(status_code=200)

        with patch("modules.api.auth.middleware.extract_jwt_from_header", return_value="x.y.z"):
            with patch("modules.api.auth.middleware.validate_jwt_token", AsyncMock(side_effect=Exception("bad jwt"))):
                await require_auth_middleware(req, cn)

        assert getattr(req.state, "auth_context", None) is None


class TestApiKeyAuth:

    @pytest.mark.asyncio
    async def test_api_key_sets_context_when_no_jwt(self):
        rt, _ = make_runtime()
        req = make_request(
            method="GET",
            path="/api/data",
            headers={"authorization": "Bearer not-a-jwt"},
            runtime=rt,
        )
        ctx = make_context(source="api_key")

        async def cn(r):
            return MagicMock(status_code=200)

        with patch("modules.api.auth.middleware.extract_jwt_from_header", return_value=None):
            with patch("modules.api.auth.middleware.extract_api_key_from_header", return_value="my-api-key"):
                with patch("modules.api.auth.middleware.validate_api_key", AsyncMock(return_value=ctx)):
                    await require_auth_middleware(req, cn)

        assert req.state.auth_context is ctx

    @pytest.mark.asyncio
    async def test_no_api_key_results_in_none_context(self):
        rt, _ = make_runtime()
        req = make_request(method="GET", path="/api/data", runtime=rt)

        async def cn(r):
            return MagicMock(status_code=200)

        with patch("modules.api.auth.middleware.extract_jwt_from_header", return_value=None):
            with patch("modules.api.auth.middleware.extract_api_key_from_header", return_value=None):
                await require_auth_middleware(req, cn)

        assert getattr(req.state, "auth_context", None) is None


class TestSessionAuth:

    @pytest.mark.asyncio
    async def test_session_cookie_sets_context(self):
        rt, _ = make_runtime()
        storage = rt.storage
        await storage.set(AUTH_USERS_NAMESPACE, "u1", {
            "user_id": "u1",
            "scopes": ["devices.read"],
            "is_admin": False,
        })
        session_id = "test-session-id"
        await storage.set(AUTH_SESSIONS_NAMESPACE, session_id, {
            "user_id": "u1",
            "expires_at": time.time() + 3600,
            "last_used": 0,
        })
        req = make_request(
            method="GET",
            path="/api/data",
            cookies={"session_id": session_id},
            runtime=rt,
        )

        async def cn(r):
            return MagicMock(status_code=200)

        with patch("modules.api.auth.middleware.extract_jwt_from_header", return_value=None):
            with patch("modules.api.auth.middleware.extract_api_key_from_header", return_value=None):
                await require_auth_middleware(req, cn)

        ctx = req.state.auth_context
        assert ctx is not None
        assert ctx.user_id == "u1"


class TestNoCredentials:

    @pytest.mark.asyncio
    async def test_no_credentials_context_is_none(self):
        rt, _ = make_runtime()
        req = make_request(method="GET", path="/api/data", runtime=rt)

        async def cn(r):
            return MagicMock(status_code=200)

        with patch("modules.api.auth.middleware.extract_jwt_from_header", return_value=None):
            with patch("modules.api.auth.middleware.extract_api_key_from_header", return_value=None):
                with patch("modules.api.auth.middleware.extract_session_from_cookie", return_value=None):
                    await require_auth_middleware(req, cn)

        assert getattr(req.state, "auth_context", None) is None

    @pytest.mark.asyncio
    async def test_no_runtime_still_calls_next(self):
        req = make_request(method="GET", path="/api/data", runtime=None)
        called = []

        async def cn(r):
            called.append(True)
            return MagicMock(status_code=200)

        with patch("modules.api.auth.middleware.extract_jwt_from_header", return_value=None):
            with patch("modules.api.auth.middleware.extract_api_key_from_header", return_value=None):
                with patch("modules.api.auth.middleware.extract_session_from_cookie", return_value=None):
                    await require_auth_middleware(req, cn)

        assert called


class TestCsrfProtection:

    @pytest.mark.asyncio
    async def test_csrf_post_with_session_no_token_returns_403(self):
        rt, _ = make_runtime()
        rt._config = SimpleNamespace(
            csrf_enabled=True,
            csrf_cookie_name="csrf_token",
            csrf_header_name="X-CSRF-Token",
            rate_limiting_enabled=False,
        )
        req = make_request(
            method="POST",
            path="/api/data",
            cookies={"session_id": "sess1"},
            runtime=rt,
        )
        ctx = make_context(source="session")

        async def cn(r):
            return MagicMock(status_code=200)

        with patch("modules.api.auth.middleware.extract_jwt_from_header", return_value=None):
            with patch("modules.api.auth.middleware.extract_api_key_from_header", return_value=None):
                with patch("modules.api.auth.middleware.validate_session", AsyncMock(return_value=ctx)):
                    with patch("modules.api.auth.middleware.extract_session_from_cookie", return_value="sess1"):
                        result = await require_auth_middleware(req, cn)

        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_csrf_post_with_matching_tokens_passes(self):
        rt, _ = make_runtime()
        token = "my-csrf-token"
        rt._config = SimpleNamespace(
            csrf_enabled=True,
            csrf_cookie_name="csrf_token",
            csrf_header_name="X-CSRF-Token",
            rate_limiting_enabled=False,
        )
        req = make_request(
            method="POST",
            path="/api/data",
            cookies={"session_id": "sess1", "csrf_token": token},
            headers={"X-CSRF-Token": token},
            runtime=rt,
        )
        ctx = make_context(source="session")
        called = []

        async def cn(r):
            called.append(True)
            return MagicMock(status_code=200)

        with patch("modules.api.auth.middleware.extract_jwt_from_header", return_value=None):
            with patch("modules.api.auth.middleware.extract_api_key_from_header", return_value=None):
                with patch("modules.api.auth.middleware.validate_session", AsyncMock(return_value=ctx)):
                    with patch("modules.api.auth.middleware.extract_session_from_cookie", return_value="sess1"):
                        await require_auth_middleware(req, cn)

        assert called

    @pytest.mark.asyncio
    async def test_csrf_disabled_no_check(self):
        rt, _ = make_runtime()
        rt._config = SimpleNamespace(
            csrf_enabled=False,
            rate_limiting_enabled=False,
        )
        req = make_request(
            method="POST",
            path="/api/data",
            cookies={"session_id": "sess1"},
            runtime=rt,
        )
        ctx = make_context(source="session")
        called = []

        async def cn(r):
            called.append(True)
            return MagicMock(status_code=200)

        with patch("modules.api.auth.middleware.extract_jwt_from_header", return_value=None):
            with patch("modules.api.auth.middleware.extract_api_key_from_header", return_value=None):
                with patch("modules.api.auth.middleware.validate_session", AsyncMock(return_value=ctx)):
                    with patch("modules.api.auth.middleware.extract_session_from_cookie", return_value="sess1"):
                        await require_auth_middleware(req, cn)

        assert called


class TestContextStoredInRequestState:

    @pytest.mark.asyncio
    async def test_context_stored_in_request_state(self):
        rt, _ = make_runtime()
        req = make_request(method="GET", path="/api/data", runtime=rt)
        ctx = make_context()

        async def cn(r):
            return MagicMock(status_code=200)

        with patch("modules.api.auth.middleware.extract_jwt_from_header", return_value="t.t.t"):
            with patch("modules.api.auth.middleware.validate_jwt_token", AsyncMock(return_value=ctx)):
                await require_auth_middleware(req, cn)

        assert hasattr(req.state, "auth_context")
        assert req.state.auth_context is ctx
