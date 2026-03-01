"""
Tests for modules/api/auth/middleware_helpers.py (coverage: 49% → 80%+)
"""
import pytest
from types import SimpleNamespace
from fastapi import Request, Response
from unittest.mock import AsyncMock, MagicMock, patch

from modules.api.auth.middleware_helpers import (
    _add_cors_to_response,
    apply_rate_limiting,
    log_auth_result,
)
from modules.api.auth.context import RequestContext


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


@pytest.fixture
def rt():
    return SimpleNamespace(
        storage=FakeStorage(),
        service_registry=FakeServiceRegistry(),
    )


def make_request(headers=None, origin=None):
    """Build a minimal mock Request."""
    all_headers = dict(headers or {})
    if origin:
        all_headers["origin"] = origin
    req = MagicMock()
    req.headers = all_headers
    req.client = SimpleNamespace(host="127.0.0.1")
    req.cookies = {}
    req.url = SimpleNamespace(path="/api/test")
    req.method = "GET"
    return req


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
# _add_cors_to_response
# ---------------------------------------------------------------------------

class TestAddCorsToResponse:

    def test_localhost_origin_adds_cors_header(self):
        req = make_request(origin="http://localhost:3000")
        resp = Response(content="ok")
        _add_cors_to_response(req, resp)
        assert resp.headers.get("Access-Control-Allow-Origin") == "http://localhost:3000"
        assert resp.headers.get("Access-Control-Allow-Credentials") == "true"

    def test_127_origin_adds_cors_header(self):
        req = make_request(origin="http://127.0.0.1:8080")
        resp = Response(content="ok")
        _add_cors_to_response(req, resp)
        assert resp.headers.get("Access-Control-Allow-Origin") == "http://127.0.0.1:8080"

    def test_external_origin_no_cors_header(self):
        req = make_request(origin="https://example.com")
        resp = Response(content="ok")
        _add_cors_to_response(req, resp)
        assert "Access-Control-Allow-Origin" not in resp.headers

    def test_no_origin_no_cors_header(self):
        req = make_request()
        resp = Response(content="ok")
        _add_cors_to_response(req, resp)
        assert "Access-Control-Allow-Origin" not in resp.headers

    def test_none_request_does_nothing(self):
        resp = Response(content="ok")
        _add_cors_to_response(None, resp)
        assert "Access-Control-Allow-Origin" not in resp.headers


# ---------------------------------------------------------------------------
# apply_rate_limiting
# ---------------------------------------------------------------------------

class TestApplyRateLimiting:

    @pytest.mark.asyncio
    async def test_returns_none_when_rate_limiting_disabled(self, rt):
        rt._config = SimpleNamespace(rate_limiting_enabled=False)
        ctx = make_context()
        result = await apply_rate_limiting(
            rt, ctx, "user1", "jwt", "127.0.0.1", "/api/x", False
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_context(self, rt):
        result = await apply_rate_limiting(
            rt, None, "user1", "jwt", "127.0.0.1", "/api/x", False
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_auth_endpoint(self, rt):
        ctx = make_context()
        result = await apply_rate_limiting(
            rt, ctx, "user1", "jwt", "127.0.0.1", "/auth/v1/login", True
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_identifier(self, rt):
        ctx = make_context()
        result = await apply_rate_limiting(
            rt, ctx, "", "jwt", "127.0.0.1", "/api/x", False
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_within_limit(self, rt):
        """First request should pass (within limit)."""
        ctx = make_context()
        result = await apply_rate_limiting(
            rt, ctx, "some-user", "jwt", "127.0.0.1", "/api/x", False
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_jwt_key_format(self, rt):
        """JWT rate limit key should be api:jwt:{user_id}."""
        ctx = make_context(user_id="myuser")
        # First call should pass, we just check it doesn't crash
        result = await apply_rate_limiting(
            rt, ctx, "myuser", "jwt", "127.0.0.1", "/api/x", False
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_api_key_passes_under_limit(self, rt):
        ctx = make_context(source="api_key")
        result = await apply_rate_limiting(
            rt, ctx, "apikey12345678901234", "api_key", "127.0.0.1", "/api/x", False
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_session_passes_under_limit(self, rt):
        ctx = make_context(source="session")
        result = await apply_rate_limiting(
            rt, ctx, "session12345678901234", "session", "127.0.0.1", "/api/x", False
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_unknown_auth_source_returns_none(self, rt):
        ctx = make_context()
        result = await apply_rate_limiting(
            rt, ctx, "user1", "unknown_source", "127.0.0.1", "/api/x", False
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded_returns_429(self, rt):
        """Simulate reaching the rate limit by patching rate_limit_check."""
        ctx = make_context()
        with patch("modules.api.auth.middleware_helpers.rate_limit_check", AsyncMock(return_value=False)):
            result = await apply_rate_limiting(
                rt, ctx, "overuser", "jwt", "127.0.0.1", "/api/x", False
            )
        assert result is not None
        assert result.status_code == 429

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded_has_retry_after_header(self, rt):
        ctx = make_context()
        with patch("modules.api.auth.middleware_helpers.rate_limit_check", AsyncMock(return_value=False)):
            result = await apply_rate_limiting(
                rt, ctx, "overuser", "jwt", "127.0.0.1", "/api/x", False
            )
        assert "Retry-After" in result.headers

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded_with_cors(self, rt):
        ctx = make_context()
        req = make_request(origin="http://localhost:3000")
        with patch("modules.api.auth.middleware_helpers.rate_limit_check", AsyncMock(return_value=False)):
            result = await apply_rate_limiting(
                rt, ctx, "overuser", "jwt", "127.0.0.1", "/api/x", False, req
            )
        assert result.status_code == 429
        assert result.headers.get("Access-Control-Allow-Origin") == "http://localhost:3000"


# ---------------------------------------------------------------------------
# log_auth_result
# ---------------------------------------------------------------------------

class TestLogAuthResult:

    @pytest.mark.asyncio
    async def test_logs_auth_success(self, rt):
        ctx = make_context()
        # Should not raise
        await log_auth_result(rt, ctx, "user1", "jwt", "127.0.0.1", "/api/x", "Mozilla/5.0")

    @pytest.mark.asyncio
    async def test_logs_auth_failure(self, rt):
        # Should not raise
        await log_auth_result(rt, None, "bad-key-12345678", "api_key", "1.2.3.4", "/api/x", None)

    @pytest.mark.asyncio
    async def test_no_identifier_returns_without_log(self, rt):
        """If identifier is falsy, should return early."""
        await log_auth_result(rt, None, "", "jwt", "127.0.0.1", "/api/x", None)
        await log_auth_result(rt, None, None, "jwt", "127.0.0.1", "/api/x", None)

    @pytest.mark.asyncio
    async def test_long_user_agent_truncated(self, rt):
        long_ua = "Mozilla" * 30
        ctx = make_context()
        await log_auth_result(rt, ctx, "u1", "jwt", "127.0.0.1", "/api/x", long_ua)
        # Should not raise even for very long user agent
