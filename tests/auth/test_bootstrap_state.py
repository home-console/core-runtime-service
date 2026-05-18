"""Bootstrap state: atomic claim and initialization checks."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.exceptions import ForbiddenError
from core.runtime.state_engine import StateEngine
from modules.api.auth import AUTH_USERS_NAMESPACE
from modules.auth import handlers as auth_handlers
from modules.auth.bootstrap_state import (
    AUTH_CONFIG_NAMESPACE,
    BOOTSTRAP_LOCK_KEY,
    BOOTSTRAP_STATE_KEY,
    check_initialized,
    try_claim_bootstrap_lock,
)
from modules.storage.port import CoreStoragePort
from tests.conftest import InMemoryStorageAdapter


@pytest.fixture
def bootstrap_runtime():
    adapter = InMemoryStorageAdapter()
    port = CoreStoragePort(adapter, StateEngine())
    runtime = MagicMock()
    runtime.storage = port.storage
    runtime.state = StateEngine()
    return runtime, adapter


@pytest.mark.asyncio
async def test_check_initialized_reads_persistent_flag(bootstrap_runtime):
    runtime, adapter = bootstrap_runtime
    await adapter.set(AUTH_CONFIG_NAMESPACE, BOOTSTRAP_STATE_KEY, {"value": True})
    assert await check_initialized(runtime) is True


@pytest.mark.asyncio
async def test_check_initialized_legacy_admin_user(bootstrap_runtime):
    runtime, adapter = bootstrap_runtime
    await adapter.set(
        AUTH_USERS_NAMESPACE,
        "admin",
        {"is_admin": True, "username": "Admin"},
    )
    assert await check_initialized(runtime) is True
    stored = await adapter.get(AUTH_CONFIG_NAMESPACE, BOOTSTRAP_STATE_KEY)
    assert stored == {"value": True}


@pytest.mark.asyncio
async def test_try_claim_bootstrap_lock_is_exclusive(bootstrap_runtime):
    runtime, _adapter = bootstrap_runtime
    assert await try_claim_bootstrap_lock(runtime) is True
    assert await try_claim_bootstrap_lock(runtime) is False


@pytest.mark.asyncio
async def test_auth_initialize_rejects_second_caller(bootstrap_runtime, monkeypatch):
    runtime, _adapter = bootstrap_runtime
    create_user = AsyncMock()
    monkeypatch.setattr(auth_handlers, "create_user", create_user)

    body = {"user_id": "admin", "password": "Secret123!", "username": "Admin"}
    result = await auth_handlers.auth_initialize(runtime, body)
    assert result["ok"] is True
    create_user.assert_awaited_once()

    with pytest.raises(ForbiddenError, match="already initialized"):
        await auth_handlers.auth_initialize(runtime, body)


@pytest.mark.asyncio
async def test_parallel_initialize_only_one_succeeds(bootstrap_runtime):
    runtime, adapter = bootstrap_runtime
    body = {"user_id": "admin", "password": "Secret123!", "username": "Admin"}

    results = await asyncio.gather(
        auth_handlers.auth_initialize(runtime, body),
        auth_handlers.auth_initialize(runtime, body),
        return_exceptions=True,
    )
    successes = [r for r in results if isinstance(r, dict) and r.get("ok")]
    failures = [r for r in results if isinstance(r, ForbiddenError)]
    assert len(successes) == 1
    assert len(failures) == 1
    admins = await adapter.list_keys(AUTH_USERS_NAMESPACE)
    assert len(admins) == 1
    assert await adapter.get(AUTH_CONFIG_NAMESPACE, BOOTSTRAP_STATE_KEY) == {"value": True}
