"""Tests for CSRF secret rotation in SecretStore."""

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from modules.security.csrf_secret import (
    CSRF_META_KEY,
    CSRF_PREVIOUS_KEY,
    CSRF_STORE_KEY,
    CsrfRotationPolicy,
    apply_csrf_secrets_to_env,
    expire_csrf_previous_if_needed,
    maybe_auto_rotate_csrf_secret,
    rotate_csrf_secret,
    sync_csrf_secrets_to_env,
)
from modules.security.secret_store import SecretStore
from modules.api.csrf_protection import CSRFProtection
from tests.security.test_secret_store import InMemoryStorageAdapter


@pytest.fixture
async def store():
    adapter = InMemoryStorageAdapter()
    s = SecretStore(adapter)
    await s.initialize("test-passphrase-for-csrf-rotation")
    yield s
    await s.close()


@pytest.mark.asyncio
async def test_rotate_csrf_secret_moves_current_to_previous(store):
    await store.put(CSRF_STORE_KEY, b"old-secret")
    report = await store.rotate_csrf_secret(generator=lambda: "new-secret")

    assert report["had_previous"] is True
    assert await store.get(CSRF_STORE_KEY) == b"new-secret"
    assert await store.get(CSRF_PREVIOUS_KEY) == b"old-secret"
    assert os.environ.get("CSRF_SECRET") == "new-secret"
    assert os.environ.get("CSRF_SECRET_PREVIOUS") == "old-secret"

    meta_raw = await store.get(CSRF_META_KEY)
    meta = json.loads(meta_raw.decode())
    assert "rotated_at" in meta
    assert "previous_expires_at" in meta


@pytest.mark.asyncio
async def test_csrf_protection_accepts_previous_secret_during_grace():
    apply_csrf_secrets_to_env("current-secret", "previous-secret")
    prot = CSRFProtection.from_env()
    session = "sess-abc"

    prev_prot = CSRFProtection(b"previous-secret")
    token = prev_prot.generate_token(session)

    prot.validate_token(token, session)


@pytest.mark.asyncio
async def test_expire_csrf_previous_after_grace(store, monkeypatch):
    await store.put(CSRF_STORE_KEY, b"current")
    await store.put(CSRF_PREVIOUS_KEY, b"stale-previous")
    expired = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    await store.put(
        CSRF_META_KEY,
        json.dumps({"previous_expires_at": expired}).encode(),
    )

    cleared = await expire_csrf_previous_if_needed(store)
    assert cleared is True
    assert await store.get(CSRF_PREVIOUS_KEY) is None


@pytest.mark.asyncio
async def test_maybe_auto_rotate_when_stale(store, monkeypatch):
    monkeypatch.setenv("RUNTIME_CSRF_ROTATION_DAYS", "30")
    await store.put(CSRF_STORE_KEY, b"aging-secret")
    old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    await store.put(CSRF_META_KEY, json.dumps({"rotated_at": old}).encode())

    report = await maybe_auto_rotate_csrf_secret(store, readonly=False)
    assert report is not None
    assert await store.get(CSRF_PREVIOUS_KEY) == b"aging-secret"
    assert (await store.get(CSRF_STORE_KEY)) != b"aging-secret"


@pytest.mark.asyncio
async def test_maybe_auto_rotate_disabled_when_days_zero(store, monkeypatch):
    monkeypatch.setenv("RUNTIME_CSRF_ROTATION_DAYS", "0")
    await store.put(CSRF_STORE_KEY, b"secret")
    old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    await store.put(CSRF_META_KEY, json.dumps({"rotated_at": old}).encode())

    assert await maybe_auto_rotate_csrf_secret(store) is None
    assert await store.get(CSRF_STORE_KEY) == b"secret"


@pytest.mark.asyncio
async def test_sync_csrf_secrets_to_env(store, monkeypatch):
    await store.put(CSRF_STORE_KEY, b"from-store")
    await store.put(CSRF_PREVIOUS_KEY, b"prev-store")
    monkeypatch.delenv("CSRF_SECRET", raising=False)
    monkeypatch.delenv("CSRF_SECRET_PREVIOUS", raising=False)

    await sync_csrf_secrets_to_env(store)
    assert os.environ["CSRF_SECRET"] == "from-store"
    assert os.environ["CSRF_SECRET_PREVIOUS"] == "prev-store"
