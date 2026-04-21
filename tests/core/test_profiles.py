import pytest

from app.profiles import (
    apply_profile_to_config,
    get_profile,
    resolve_module_specs_for_profile,
)
from core.runtime.config import Config


def test_get_profile_minimal_modules():
    p = get_profile("minimal")
    assert [s.name for s in p.modules] == ["logger", "api", "auth", "devices"]


def test_get_profile_unknown_raises_keyerror():
    with pytest.raises(KeyError):
        get_profile("unknown")


def test_apply_profile_to_config_applies_overrides(monkeypatch: pytest.MonkeyPatch):
    for k in [
        "RUNTIME_ORCHESTRATION_BACKEND",
        "RUNTIME_RATE_LIMITING_ENABLED",
        "RUNTIME_SERVICE_CALL_TIMEOUT",
        "RUNTIME_SHUTDOWN_TIMEOUT",
    ]:
        monkeypatch.delenv(k, raising=False)

    p = get_profile("minimal")
    cfg = Config()
    out = apply_profile_to_config(p, cfg)

    assert out.orchestration_backend == "none"
    assert out.rate_limiting_enabled is False
    assert out.service_call_timeout == 60.0
    assert out.shutdown_timeout == 5


def test_apply_profile_to_config_prod_forces_overrides(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RUNTIME_RATE_LIMITING_ENABLED", "false")
    monkeypatch.setenv("RUNTIME_RATE_LIMIT_REQUESTS", "1000")
    monkeypatch.setenv("RUNTIME_RATE_LIMIT_WINDOW", "999")
    monkeypatch.setenv("RUNTIME_LOG_FORMAT", "text")
    monkeypatch.setenv("RUNTIME_ORCHESTRATION_BACKEND", "none")

    p = get_profile("prod")
    cfg = Config.from_env()  # читает env и валидирует
    out = apply_profile_to_config(p, cfg)

    assert out.orchestration_backend == "docker"
    assert out.rate_limiting_enabled is True
    assert out.rate_limit_requests == 60
    assert out.rate_limit_window == 60
    assert out.log_format == "json"


def test_resolve_module_specs_for_profile_none_returns_app_modules():
    cfg = Config()
    specs = resolve_module_specs_for_profile(None, cfg)

    from app.bootstrap import APP_MODULES

    assert [s.name for s in specs] == [s.name for s in APP_MODULES]


def test_resolve_module_specs_for_profile_minimal_returns_4_modules():
    cfg = Config()
    specs = resolve_module_specs_for_profile("minimal", cfg)
    assert [s.name for s in specs] == ["logger", "api", "auth", "devices"]


def test_resolve_module_specs_uses_modules_config_over_profile():
    cfg = Config(modules_config="logger:true,api:true")
    specs = resolve_module_specs_for_profile("minimal", cfg)
    assert [s.name for s in specs] == ["logger", "api"]


def test_minimal_profile_order_has_valid_dependencies():
    p = get_profile("minimal")
    names = {s.name for s in p.modules}
    for s in p.modules:
        for dep in s.dependencies:
            assert dep in names

