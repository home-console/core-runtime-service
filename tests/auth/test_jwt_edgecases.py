import pytest
import time
import jwt as pyjwt
from modules.api.auth import jwt_tokens as jwt_mod
from modules.api.auth.constants import JWT_ALGORITHM


@pytest.mark.asyncio
async def test_expired_token(runtime):
    secret = await jwt_mod.get_or_create_jwt_secret(runtime)
    # Create token already expired
    token = jwt_mod.generate_access_token("u1", ["r"], False, secret, expiration_seconds=-1)
    assert jwt_mod.validate_access_token(token, secret) is None
    assert await jwt_mod.validate_jwt_token(runtime, token) is None


@pytest.mark.asyncio
async def test_invalid_signature(runtime):
    secret = await jwt_mod.get_or_create_jwt_secret(runtime)
    # Generate token with a different secret
    bad_token = jwt_mod.generate_access_token("u2", ["r"], False, "wrong-secret", expiration_seconds=60)
    assert jwt_mod.validate_access_token(bad_token, secret) is None
    assert await jwt_mod.validate_jwt_token(runtime, bad_token) is None


def test_malformed_token_handling():
    # Totally invalid string
    assert jwt_mod.validate_access_token("not-a-jwt", "s") is None


@pytest.mark.asyncio
async def test_wrong_type_token(runtime):
    # Create a token with type 'refresh' and ensure it's rejected by access validator
    secret = await jwt_mod.get_or_create_jwt_secret(runtime)
    payload = {"user_id": "u3", "scopes": ["r"], "is_admin": False, "iat": time.time(), "exp": time.time() + 60, "type": "refresh"}
    token = pyjwt.encode(payload, secret, algorithm=JWT_ALGORITHM)

    assert jwt_mod.validate_access_token(token, secret) is None
    assert await jwt_mod.validate_jwt_token(runtime, token) is None
