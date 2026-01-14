import pytest
from types import SimpleNamespace

from modules.api.auth.rate_limiting import rate_limit_check
from modules.api.auth.middleware_helpers import apply_rate_limiting
from modules.api.auth.constants import RATE_LIMIT_AUTH_ATTEMPTS, AUTH_RATE_LIMITS_NAMESPACE


@pytest.mark.asyncio
async def test_rate_limit_auth_exceeded(runtime):
    identifier = "1.2.3.4"
    # perform attempts equal to limit
    for _ in range(RATE_LIMIT_AUTH_ATTEMPTS):
        ok = await rate_limit_check(runtime, identifier, "auth")
        assert ok is True

    # next attempt should be blocked
    ok = await rate_limit_check(runtime, identifier, "auth")
    assert ok is False


@pytest.mark.asyncio
async def test_apply_rate_limiting_api_path(runtime):
    # Construct a RequestContext-like object
    ctx = SimpleNamespace(user_id="u1")

    # identifier used by apply_rate_limiting for jwt
    identifier = "u1"

    # Exhaust API limit by calling apply_rate_limiting many times
    # The default API limit is high; we simulate lowering it by directly calling rate_limit_check
    # Here we'll just reuse rate_limit_check with the api key to trigger block
    api_key = "apikey-sample-000"
    # call rate_limit_check for the same key until blocked
    # choose limit_type 'api' to use API defaults
    for i in range(5):
        await rate_limit_check(runtime, f"api:test:{i}", "api")

    # Now directly test apply_rate_limiting does not error and returns None when under limit
    resp = await apply_rate_limiting(runtime, ctx, identifier, "jwt", "127.0.0.1", "/api/x", False)
    assert resp is None


@pytest.mark.asyncio
async def test_rate_limit_fail_open_on_storage_error(runtime):
    # Make storage.get raise to simulate storage failure
    async def bad_get(namespace, key):
        raise Exception("storage down")

    runtime.storage.get = bad_get

    # Should return True (fail-open)
    ok = await rate_limit_check(runtime, "any", "auth")
    assert ok is True
