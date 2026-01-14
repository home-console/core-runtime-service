import pytest
from modules.api.auth import revocation
from modules.api.auth import jwt_tokens as jwt
from modules.api.auth.constants import AUTH_USERS_NAMESPACE


@pytest.mark.asyncio
async def test_revocation_api_key_and_session(runtime):
    # Revoke api key
    await revocation.revoke_api_key(runtime, "key-123")
    assert await revocation.is_revoked(runtime, "key-123", "api_key") is True

    # Revoke session
    await revocation.revoke_session(runtime, "sess-abc")
    assert await revocation.is_revoked(runtime, "sess-abc", "session") is True


@pytest.mark.asyncio
async def test_revocation_refresh_token(runtime):
    # Prepare user for refresh flow
    await runtime.storage.set(AUTH_USERS_NAMESPACE, "ruser", {"scopes": ["read"], "is_admin": False})

    # Create refresh token
    refresh_token = await jwt.create_refresh_token(runtime, "ruser", expiration_seconds=60)
    assert isinstance(refresh_token, str)

    # Revoke and check
    await revocation.revoke_refresh_token(runtime, refresh_token)
    assert await revocation.is_revoked(runtime, refresh_token, "refresh_token") is True
