import pytest
from modules.api.auth import audit
from modules.api.auth import jwt_tokens as jwt_mod
from modules.api.auth import revocation
from modules.api.auth.constants import AUTH_AUDIT_LOG_NAMESPACE, AUTH_USERS_NAMESPACE


def _find_audit(runtime, event_type=None, subject_contains=None):
    entries = runtime.storage._data.get(AUTH_AUDIT_LOG_NAMESPACE, {}).values()
    for e in entries:
        if event_type and e.get("event_type") != event_type:
            continue
        if subject_contains and subject_contains not in e.get("subject", ""):
            continue
        return e
    return None


@pytest.mark.asyncio
async def test_audit_log_direct(runtime):
    await audit.audit_log_auth_event(runtime, "test_event", "subject-xyz", {"k": "v"}, success=True)
    e = _find_audit(runtime, event_type="test_event", subject_contains="subject-xyz")
    assert e is not None
    assert e["success"] is True


@pytest.mark.asyncio
async def test_audit_on_refresh_and_revoke(runtime):
    # Prepare user
    await runtime.storage.set(AUTH_USERS_NAMESPACE, "auuser", {"scopes": ["r"], "is_admin": False})

    # create_refresh_token should produce an audit entry
    rt = await jwt_mod.create_refresh_token(runtime, "auuser", expiration_seconds=60)
    e1 = _find_audit(runtime, event_type="refresh_token_created")
    assert e1 is not None

    # revoke_refresh_token should produce an audit entry
    await revocation.revoke_refresh_token(runtime, rt)
    e2 = _find_audit(runtime, event_type="refresh_token_revoked")
    assert e2 is not None
