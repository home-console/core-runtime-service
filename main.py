"""
Точка входа Home Console Runtime.

Задача: загрузить env → построить storage-стек → открыть SecretStore →
bootstrap секреты → запустить runtime.

Вся логика работы с env и секретами — в app/env_bootstrap.py.
"""
import asyncio
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

from app.env_bootstrap import (
    bootstrap_runtime_secrets,
    env_flag,
    load_dotenv,
    open_secret_store,
    preflight_check,
    probe_storage_read,
    secrets_source_mode,
)
from app.bootstrap import auto_load_plugins_if_enabled, build_runtime, record_plugin_load_error
from app.bootstrap import resolve_module_specs_for_profile
from core.runtime.config import Config
from core.runtime.state_engine import StateEngine
from modules.storage.factory import build_storage_stack

load_dotenv()


async def main() -> None:
    config = _build_config()
    _ensure_data_dirs(config)

    state_engine = StateEngine()
    storage_stack = await build_storage_stack(config, state_engine)
    await probe_storage_read(storage_stack)

    readonly = env_flag("RUNTIME_BOOTSTRAP_READONLY")
    source_mode = secrets_source_mode()

    secret_store = None
    report: dict[str, list[str]] = {"imported_from_env": [], "generated": [], "missing_required": []}
    try:
        secret_store = await open_secret_store(storage_stack)
        report = await bootstrap_runtime_secrets(secret_store, source_mode=source_mode, readonly=readonly)
        if report["missing_required"]:
            raise RuntimeError(
                "Missing required bootstrap secrets: " + ", ".join(report["missing_required"])
            )
    except Exception as e:
        if getattr(config, "env", "production") == "production":
            raise
        print(f"[Runtime] SecretStore not available: {e}")
        if readonly:
            raise

    if readonly:
        print("[Runtime] Bootstrap probe OK")
        print(f"[Runtime] Secret source mode: {source_mode}")
        if report["imported_from_env"]:
            print("[Runtime] Probe note: store missing for " + ", ".join(report["imported_from_env"]))
        await _close_storage(storage_stack)
        return

    preflight_check()

    profile_name = os.getenv("RUNTIME_PROFILE")
    module_specs = resolve_module_specs_for_profile(profile_name, config)
    print(f"[Runtime] Modules ({len(module_specs)}): {[s.name for s in module_specs]}")

    runtime = await build_runtime(
        storage_port=storage_stack.core_port,
        config=config,
        vault_port=storage_stack.vault_port,
        state_engine=state_engine,
        storage_manager=storage_stack.manager,
        module_specs=module_specs,
    )
    if secret_store is not None:
        runtime.secret_store = secret_store

    print(f"[Runtime] Storage: {config.storage_mode}/{config.storage_type}")
    try:
        await auto_load_plugins_if_enabled(runtime, config)
    except Exception as e:
        record_plugin_load_error(runtime, "__auto_load__", str(e))
        print(f"[Runtime] Plugin auto-load failed: {e}", file=sys.stderr)
    else:
        load_errors = getattr(runtime, "plugin_load_errors", {}) or {}
        for name, err in load_errors.items():
            print(f"[Runtime] Plugin load error ({name}): {err}", file=sys.stderr)

    await runtime.run()
    await _teardown(runtime, storage_stack)
    sys.exit(0)


# ── helpers ───────────────────────────────────────────────────────────────────

def _build_config() -> Config:
    profile_name = os.getenv("RUNTIME_PROFILE")
    config = Config.from_env()
    if not profile_name:
        return config
    from app.profiles import PROFILES, apply_profile_to_config, get_profile
    try:
        profile = get_profile(profile_name)
        config = apply_profile_to_config(profile, config)
        config.validate()
        print(f"[Runtime] Profile: {profile.name} — {profile.description}")
    except KeyError:
        print(f"[Runtime] Unknown RUNTIME_PROFILE={profile_name!r}. Available: {list(PROFILES.keys())}")
        sys.exit(1)
    return config


def _ensure_data_dirs(config: Config) -> None:
    if config.storage_type == "sqlite":
        Path(config.db_path).parent.mkdir(parents=True, exist_ok=True)
    if config.storage_mode == "dual" and config.vault_storage_type == "sqlite" and config.vault_db_path:
        Path(config.vault_db_path).parent.mkdir(parents=True, exist_ok=True)


async def _teardown(runtime: object, storage_stack: object) -> None:
    for svc_name in ("event_bus", "service_registry"):
        try:
            svc = getattr(getattr(runtime, "services", None), svc_name, None)
            if svc and callable(getattr(svc, "stop", None)):
                await svc.stop()
        except Exception as e:
            logger.warning("Failed to stop %s during teardown: %s", svc_name, e)
    await _close_storage(storage_stack)


async def _close_storage(storage_stack: object) -> None:
    try:
        await storage_stack.manager.close()
        logger.info("Storage closed")
    except Exception as e:
        logger.warning("Failed to close storage: %s", e)


if __name__ == "__main__":
    asyncio.run(main())
