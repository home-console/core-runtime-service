"""
Точка входа в приложение Home Console.

main.py строит config/storage/runtime, регистрирует модули и вызывает runtime.run().
HTTP (FastAPI/uvicorn) полностью в модуле api; Runtime вызывает transport-контракт api.run_transport() после start().
"""

import asyncio
import os
import sys
from pathlib import Path

from app.bootstrap import (
    APP_MODULES,
    auto_load_plugins_if_enabled,
    build_runtime,
    parse_module_specs,
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


def _validate_security_configuration() -> None:
    """Fail-fast проверка обязательной security-конфигурации перед стартом runtime."""
    result = check_security_env()
    warnings = result.get("warnings", [])
    for warning in warnings:
        print(f"[Runtime][Security Warning] {warning}")


def _resolve_secret_store_passphrase() -> str:
    """Получить passphrase для SecretStore без insecure fallback значения."""
    passphrase = (os.getenv("AGENT_SECRET_STORE_PASSPHRASE") or "").strip()
    if not passphrase:
        raise RuntimeError("AGENT_SECRET_STORE_PASSPHRASE is required")
    return passphrase


async def main() -> None:
    _validate_security_configuration()
    config = Config.from_env()
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
    runtime = await build_runtime(
        storage_port=storage_stack.core_port,
        config=config,
        vault_port=storage_stack.vault_port,
        state_engine=state_engine,
        storage_manager=storage_stack.manager,
        module_specs=parse_module_specs(config),
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
    except Exception as e:
        if getattr(config, "env", "production") == "production":
            raise
        print(f"[Runtime] SecretStore not available: {e}")

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
