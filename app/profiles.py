from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import Any

from core.module_spec import ModuleSpec
from core.runtime.config import Config


@dataclass(frozen=True)
class RuntimeProfile:
    name: str
    description: str
    modules: list[ModuleSpec]
    # Overrides для Config — только те поля которые профиль меняет
    config_overrides: dict[str, Any]


def _copy_spec(spec: ModuleSpec) -> ModuleSpec:
    return ModuleSpec(
        name=spec.name,
        required=spec.required,
        dependencies=list(spec.dependencies or []),
    )


def _specs_by_name() -> dict[str, ModuleSpec]:
    # Local import to avoid importing app-layer too early.
    from app.bootstrap import APP_MODULES

    return {s.name: s for s in APP_MODULES}


def _spec_list(names: list[str]) -> list[ModuleSpec]:
    by_name = _specs_by_name()
    specs: list[ModuleSpec] = []
    for name in names:
        if name not in by_name:
            raise KeyError(f"Unknown module in profile: {name}")
        base = by_name[name]
        specs.append(_copy_spec(base))
    return specs


def _required_plus_extras(*, include: set[str], exclude: set[str]) -> list[ModuleSpec]:
    from app.bootstrap import APP_MODULES

    by_name = {s.name: s for s in APP_MODULES}
    selected: list[ModuleSpec] = []
    for s in APP_MODULES:
        if s.name in exclude:
            continue
        if s.required or s.name in include:
            selected.append(_copy_spec(s))
    # extras that are not in APP_MODULES order (shouldn't happen, but keep deterministic)
    for name in sorted(include):
        if name in exclude:
            continue
        if name not in by_name:
            raise KeyError(f"Unknown module in profile: {name}")
        if name not in {s.name for s in selected}:
            selected.append(_copy_spec(by_name[name]))
    return selected


def _all_app_modules() -> list[ModuleSpec]:
    from app.bootstrap import APP_MODULES

    return [_copy_spec(s) for s in APP_MODULES]


PROFILES: dict[str, RuntimeProfile] = {
    "minimal": RuntimeProfile(
        name="minimal",
        description="Минимальный стек для разработки. Только logger+api+auth+devices.",
        modules=_spec_list(["logger", "api", "auth", "devices"]),
        config_overrides={
            "orchestration_backend": "none",
            "rate_limiting_enabled": False,
            "service_call_timeout": 60.0,
            "shutdown_timeout": 5,
        },
    ),
    "dev": RuntimeProfile(
        name="dev",
        description="Стек разработки. Все core-модули без agent и product_api.",
        modules=_required_plus_extras(
            include={"credentials", "automation"},
            exclude={"agent", "product_api"},
        ),
        config_overrides={
            "orchestration_backend": "none",
            "rate_limiting_enabled": False,
        },
    ),
    "full": RuntimeProfile(
        name="full",
        description="Полный стек. Все модули включая agent и product_api.",
        modules=_all_app_modules(),
        config_overrides={},
    ),
    "prod": RuntimeProfile(
        name="prod",
        description="Production. Полный стек, json-логи, strict rate limiting.",
        modules=_all_app_modules(),
        config_overrides={
            "orchestration_backend": "docker",
            "rate_limiting_enabled": True,
            "rate_limit_requests": 60,
            "rate_limit_window": 60,
            "log_format": "json",
        },
    ),
}


def get_profile(name: str) -> RuntimeProfile:
    """Вернуть профиль по имени. KeyError если не найден."""
    return PROFILES[name]


_CONFIG_ENV_KEYS: dict[str, str] = {
    "orchestration_backend": "RUNTIME_ORCHESTRATION_BACKEND",
    "rate_limiting_enabled": "RUNTIME_RATE_LIMITING_ENABLED",
    "service_call_timeout": "RUNTIME_SERVICE_CALL_TIMEOUT",
    "shutdown_timeout": "RUNTIME_SHUTDOWN_TIMEOUT",
    "rate_limit_requests": "RUNTIME_RATE_LIMIT_REQUESTS",
    "rate_limit_window": "RUNTIME_RATE_LIMIT_WINDOW",
    "log_format": "RUNTIME_LOG_FORMAT",
}


def apply_profile_to_config(profile: RuntimeProfile, config: Config) -> Config:
    """
    Применить config_overrides профиля к существующему Config.
    Возвращает новый Config с применёнными overrides.
    ENV переменные имеют приоритет над profile overrides — если ENV уже задала
    значение, profile его не перезаписывает.
    Исключение: RUNTIME_PROFILE=prod принудительно применяет все свои overrides
    даже если ENV задала другое значение (безопасность важнее).
    """
    forced = profile.name == "prod"

    updates: dict[str, Any] = {}
    for field_name, value in profile.config_overrides.items():
        env_key = _CONFIG_ENV_KEYS.get(field_name)
        if not forced and env_key is not None and os.getenv(env_key) is not None:
            continue
        updates[field_name] = value

    if not updates:
        return config
    return replace(config, **updates)


def resolve_module_specs_for_profile(
    profile_name: str | None,
    config: Config,
) -> list[ModuleSpec]:
    """
    Определить список модулей с учётом профиля и RUNTIME_MODULES ENV.

    Приоритет (от высшего к низшему):
    1. RUNTIME_MODULES в ENV — если задан, всегда используется как есть
    2. RUNTIME_PROFILE — если задан, берёт модули из профиля
    3. APP_MODULES — дефолт

    Returns:
        Отсортированный список ModuleSpec (ModuleDependencySorter уже применён)
    """
    raw = getattr(config, "modules_config", None)
    if raw:
        from app.bootstrap import parse_module_specs

        return parse_module_specs(config)

    if profile_name:
        return list(get_profile(profile_name).modules)

    from app.bootstrap import APP_MODULES

    return APP_MODULES

