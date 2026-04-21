"""
Точка входа в приложение Home Console.

main.py строит config/storage/runtime, регистрирует модули и вызывает runtime.run().
HTTP (FastAPI/uvicorn) полностью в модуле api; Runtime вызывает transport-контракт api.run_transport() после start().
"""

import asyncio
import os
import sys
from pathlib import Path
import secrets
from typing import Callable, Optional

from app.bootstrap import (
    APP_MODULES,
    auto_load_plugins_if_enabled,
    build_runtime,
)
from core.runtime.config import Config
from core.runtime.state_engine import StateEngine
from modules.security import check_security_env
from modules.storage.factory import build_storage_stack


def _load_dotenv() -> None:
    def _load_file(path: Path) -> None:
        if not path.is_file():
            return
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip().strip("'\"").replace("\\n", "\n").strip()
                        if key and key not in os.environ:
                            os.environ[key] = value
        except OSError:
            pass

    _load_file(Path(__file__).resolve().parent / ".env")
    _load_file(Path.cwd() / ".env")


_load_dotenv()


def _resolve_secret_store_passphrase() -> str:
    """Получить master key для SecretStore без insecure fallback значения."""
    passphrase = (os.getenv("RUNTIME_MASTER_KEY") or "").strip()
    if not passphrase:
        raise RuntimeError("RUNTIME_MASTER_KEY is required")
    return passphrase


async def _bootstrap_runtime_secrets(secret_store: object) -> None:
    """
    Ensure core runtime secrets exist in SecretStore, and expose them via env for legacy readers.

    Goal: single external bootstrap secret (RUNTIME_MASTER_KEY). Everything else lives in SecretStore.
    """
    # Late imports to keep main.py light and avoid importing optional deps too early.
    from sdk.security import TokenEncryption

    async def _ensure_env_from_store(
        env_key: str, store_key: str, generate: Optional[Callable[[], str]]
    ) -> None:
        current = (os.getenv(env_key) or "").strip()
        if current:
            return

        val_bytes = await secret_store.get(store_key)  # type: ignore[attr-defined]
        if val_bytes:
            os.environ[env_key] = val_bytes.decode("utf-8")
            return

        if generate is None:
            return

        generated = generate()
        os.environ[env_key] = generated
        await secret_store.put(store_key, generated.encode("utf-8"))  # type: ignore[attr-defined]

    # Required for admin CSRF protection.
    await _ensure_env_from_store(
        env_key="CSRF_SECRET",
        store_key="runtime.csrf_secret",
        generate=lambda: secrets.token_hex(32),
    )

    # Required for OAuth token encryption at rest (Fernet base64 key).
    await _ensure_env_from_store(
        env_key="OAUTH_ENCRYPTION_KEY",
        store_key="runtime.oauth_encryption_key",
        generate=TokenEncryption.generate_key,
    )

    # Optional: only needed if Yandex OAuth/plugins are used.
    await _ensure_env_from_store(
        env_key="YANDEX_CLIENT_SECRET",
        store_key="yandex.client_secret",
        generate=None,
    )


def _validate_security_configuration() -> None:
    """Fail-fast проверка обязательной security-конфигурации перед стартом runtime."""
    result = check_security_env()
    warnings = result.get("warnings", [])
    for warning in warnings:
        print(f"[Runtime][Security Warning] {warning}")


def _preflight_required_env() -> None:
    """
    Pre-flight проверка env vars с понятным списком проблем.

    Важно: CSRF_SECRET и OAUTH_ENCRYPTION_KEY могут быть проброшены из SecretStore
    при старте, поэтому эту проверку вызываем ПОСЛЕ bootstrap секретов.
    """
    missing: list[str] = []

    # Always required (bootstrap secret)
    if not (os.getenv("RUNTIME_MASTER_KEY") or "").strip():
        missing.append("RUNTIME_MASTER_KEY")

    # Security secrets must exist if CSRF is enabled (default true).
    csrf_enabled = (os.getenv("RUNTIME_CSRF_ENABLED") or "true").lower().strip() == "true"
    if csrf_enabled:
        if not (os.getenv("CSRF_SECRET") or "").strip():
            missing.append("CSRF_SECRET")
        if not (os.getenv("OAUTH_ENCRYPTION_KEY") or "").strip():
            missing.append("OAUTH_ENCRYPTION_KEY")

    if missing:
        hint = (
            "Missing required environment variables:\n"
            + "\n".join(f"  - {k}" for k in missing)
        )
        raise RuntimeError(hint)


async def main() -> None:
    profile_name = os.getenv("RUNTIME_PROFILE")  # "minimal" | "dev" | "full" | "prod" | None
    config = Config.from_env()
    if profile_name:
        from app.profiles import PROFILES, apply_profile_to_config, get_profile

        try:
            profile = get_profile(profile_name)
            config = apply_profile_to_config(profile, config)
            # После overrides может потребоваться повторная валидация.
            config.validate()
            print(f"[Runtime] Profile: {profile.name} — {profile.description}")
        except KeyError:
            available = list(PROFILES.keys())
            print(
                f"[Runtime] Unknown RUNTIME_PROFILE={profile_name!r}. Available: {available}"
            )
            sys.exit(1)

    if config.storage_type == "sqlite":
        Path(config.db_path).parent.mkdir(parents=True, exist_ok=True)
    if (
        config.storage_mode == "dual"
        and config.vault_storage_type == "sqlite"
        and config.vault_db_path
    ):
        Path(config.vault_db_path).parent.mkdir(parents=True, exist_ok=True)

    state_engine = StateEngine()
    storage_stack = await build_storage_stack(config, state_engine)

    from app.profiles import resolve_module_specs_for_profile

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

    # SecretStore для inspector (debug) и credentials: один раз при старте
    try:
        from modules.security import SecretStore, SecretStoreStorageAdapter

        backend = (
            storage_stack.manager.get_vault()
            if storage_stack.manager.is_dual_mode
            else storage_stack.manager.get_core()
        )
        wrapper = SecretStoreStorageAdapter(backend)
        secret_store = SecretStore(wrapper)
        passphrase = _resolve_secret_store_passphrase()
        # Сначала открыть существующий store (salt уже в vault), иначе — новая инициализация.
        # Раньше вызывали initialize() первым — он перезаписывал salt, после перезапуска секреты не расшифровывались.
        try:
            await secret_store.open_with_passphrase(passphrase)
        except RuntimeError as e:
            if "not initialized" in str(e).lower():
                await secret_store.initialize(passphrase)
            else:
                raise
        runtime.secret_store = secret_store
        await _bootstrap_runtime_secrets(secret_store)
    except Exception as e:
        if getattr(config, "env", "production") == "production":
            raise
        print(f"[Runtime] SecretStore not available: {e}")

    _preflight_required_env()
    _validate_security_configuration()

    print(f"[Runtime] Storage mode: {config.storage_mode} ({config.storage_type})")
    if config.storage_mode == "dual":
        print(f"[Runtime] Vault storage: {config.vault_storage_type}")
    print("[Runtime] Регистрация модулей...")
    try:
        modules = runtime.module_manager.list_modules()
        if modules:
            print(f"[Runtime] Модули: {modules}")
    except Exception:
        pass
    try:
        await auto_load_plugins_if_enabled(runtime, config)
    except Exception as e:
        print(f"[Runtime] Plugin auto-load skipped: {e}")

    await runtime.run()

    try:
        await storage_stack.manager.close()
        print("[Runtime] Storage закрыт")
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
