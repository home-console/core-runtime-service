"""
Bootstrap security tests.

Проверяем функции из app.env_bootstrap и modules.security.master_key
(раньше жили в main.py).
"""
import asyncio
import pytest

import app.env_bootstrap as env_bootstrap
from modules.security.master_key import resolve_master_key_passphrase


# ── master key resolution ────────────────────────────────────────────────────

def test_resolve_master_key_from_env(monkeypatch):
    monkeypatch.setenv("RUNTIME_MASTER_KEY", "strong-pass")
    monkeypatch.delenv("RUNTIME_MASTER_KEY_FILE", raising=False)
    assert resolve_master_key_passphrase() == "strong-pass"


def test_resolve_master_key_raises_when_missing(monkeypatch):
    monkeypatch.delenv("RUNTIME_MASTER_KEY", raising=False)
    monkeypatch.delenv("RUNTIME_MASTER_KEY_FILE", raising=False)
    with pytest.raises(RuntimeError, match="RUNTIME_MASTER_KEY is required"):
        resolve_master_key_passphrase()


def test_resolve_master_key_from_file(tmp_path, monkeypatch):
    key_file = tmp_path / "master.key"
    key_file.write_text("file-master-key\n", encoding="utf-8")
    monkeypatch.setenv("RUNTIME_MASTER_KEY_FILE", str(key_file))
    monkeypatch.delenv("RUNTIME_MASTER_KEY", raising=False)
    assert resolve_master_key_passphrase() == "file-master-key"


def test_resolve_master_key_file_takes_priority(tmp_path, monkeypatch):
    key_file = tmp_path / "master.key"
    key_file.write_text("from-file", encoding="utf-8")
    monkeypatch.setenv("RUNTIME_MASTER_KEY_FILE", str(key_file))
    monkeypatch.setenv("RUNTIME_MASTER_KEY", "from-env")
    assert resolve_master_key_passphrase() == "from-file"


# ── secrets_source_mode ───────────────────────────────────────────────────────

def test_secrets_source_mode_default(monkeypatch):
    monkeypatch.delenv("RUNTIME_SECRETS_SOURCE", raising=False)
    assert env_bootstrap.secrets_source_mode() == "store+env"


def test_secrets_source_mode_invalid(monkeypatch):
    monkeypatch.setenv("RUNTIME_SECRETS_SOURCE", "bad_value")
    with pytest.raises(RuntimeError, match="RUNTIME_SECRETS_SOURCE must be one of"):
        env_bootstrap.secrets_source_mode()


# ── bootstrap_runtime_secrets ─────────────────────────────────────────────────

class _FakeSecretStore:
    def __init__(self, initial: dict[str, str] | None = None):
        self._data = dict(initial or {})
        self.put_calls: list[str] = []

    async def get(self, key: str):
        val = self._data.get(key)
        return val.encode() if val is not None else None

    async def put(self, key: str, value: bytes):
        self._data[key] = value.decode()
        self.put_calls.append(key)


def test_bootstrap_store_env_imports_env_into_store(monkeypatch):
    monkeypatch.setenv("CSRF_SECRET", "csrf-from-env")
    monkeypatch.setenv("OAUTH_ENCRYPTION_KEY", "oauth-from-env")
    monkeypatch.delenv("YANDEX_CLIENT_SECRET", raising=False)

    store = _FakeSecretStore()
    report = asyncio.run(
        env_bootstrap.bootstrap_runtime_secrets(store, source_mode="store+env", readonly=False)
    )

    assert "CSRF_SECRET" in report["imported_from_env"]
    assert "OAUTH_ENCRYPTION_KEY" in report["imported_from_env"]
    assert report["missing_required"] == []
    assert "runtime.csrf_secret" in store.put_calls
    assert "runtime.oauth_encryption_key" in store.put_calls


def test_bootstrap_store_only_readonly_reports_missing(monkeypatch):
    monkeypatch.delenv("CSRF_SECRET", raising=False)
    monkeypatch.delenv("OAUTH_ENCRYPTION_KEY", raising=False)

    store = _FakeSecretStore()
    report = asyncio.run(
        env_bootstrap.bootstrap_runtime_secrets(store, source_mode="store", readonly=True)
    )

    assert "CSRF_SECRET" in report["missing_required"]
    assert "OAUTH_ENCRYPTION_KEY" in report["missing_required"]
    assert store.put_calls == []


def test_bootstrap_store_prefers_store_over_env(monkeypatch):
    monkeypatch.setenv("CSRF_SECRET", "env-value")

    store = _FakeSecretStore({"runtime.csrf_secret": "store-value"})
    report = asyncio.run(
        env_bootstrap.bootstrap_runtime_secrets(store, source_mode="store+env", readonly=False)
    )

    assert report["missing_required"] == []
    assert report["imported_from_env"] == [] or "CSRF_SECRET" not in report["imported_from_env"]
    import os
    assert os.environ.get("CSRF_SECRET") == "store-value"


def test_bootstrap_store_generates_when_missing(monkeypatch):
    monkeypatch.delenv("CSRF_SECRET", raising=False)
    monkeypatch.delenv("OAUTH_ENCRYPTION_KEY", raising=False)

    store = _FakeSecretStore()
    report = asyncio.run(
        env_bootstrap.bootstrap_runtime_secrets(store, source_mode="store", readonly=False)
    )

    assert report["missing_required"] == []
    assert "CSRF_SECRET" in report["generated"]
    assert "OAUTH_ENCRYPTION_KEY" in report["generated"]
    assert "runtime.csrf_secret" in store.put_calls
