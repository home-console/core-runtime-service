import pytest
from modules.api.auth import jwt_tokens as jwt
from modules.api.auth.revocation import is_revoked
from modules.api.auth.constants import AUTH_USERS_NAMESPACE


@pytest.mark.asyncio
async def test_jwt_generate_validate_and_refresh(runtime):
    # Prepare user
    await runtime.storage.set(AUTH_USERS_NAMESPACE, "testuser", {"scopes": ["read"], "is_admin": False})

    # Secret generation
    secret = await jwt.get_or_create_jwt_secret(runtime)
    assert isinstance(secret, str) and len(secret) > 0

    # Generate access token and validate payload
    token = jwt.generate_access_token("testuser", ["read"], False, secret, expiration_seconds=60)
    assert isinstance(token, str)

    payload = await jwt.validate_access_token(token, secret)
    assert payload is not None
    assert payload.get("user_id") == "testuser"

    # Validate as RequestContext
    ctx = await jwt.validate_jwt_token(runtime, token)
    assert ctx is not None
    assert getattr(ctx, "user_id", None) == "testuser"

    # Create refresh token and refresh access
    refresh_token = await jwt.create_refresh_token(runtime, "testuser", expiration_seconds=120)
    assert isinstance(refresh_token, str)

    access_token2, new_refresh = await jwt.refresh_access_token(runtime, refresh_token, rotate_refresh=True)
    assert isinstance(access_token2, str)
    assert isinstance(new_refresh, str)

    # Old refresh token should be revoked after rotation
    revoked = await is_revoked(runtime, refresh_token, "refresh_token")
    assert revoked is True
