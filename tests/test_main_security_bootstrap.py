import pytest

import main as main_module


def test_validate_security_configuration_calls_check(monkeypatch):
    called = {"value": False}

    def _fake_check():
        called["value"] = True
        return {"errors": [], "warnings": []}

    monkeypatch.setattr(main_module, "check_security_env", _fake_check)

    main_module._validate_security_configuration()

    assert called["value"] is True


def test_validate_security_configuration_raises_on_invalid_env(monkeypatch):
    def _fake_check():
        raise RuntimeError("security env invalid")

    monkeypatch.setattr(main_module, "check_security_env", _fake_check)

    with pytest.raises(RuntimeError, match="security env invalid"):
        main_module._validate_security_configuration()


def test_resolve_secret_store_passphrase_returns_value(monkeypatch):
    monkeypatch.setenv("AGENT_SECRET_STORE_PASSPHRASE", "strong-pass")

    assert main_module._resolve_secret_store_passphrase() == "strong-pass"


def test_resolve_secret_store_passphrase_raises_on_missing(monkeypatch):
    monkeypatch.delenv("AGENT_SECRET_STORE_PASSPHRASE", raising=False)

    with pytest.raises(RuntimeError, match="AGENT_SECRET_STORE_PASSPHRASE is required"):
        main_module._resolve_secret_store_passphrase()
