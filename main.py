"""
Точка входа в приложение Home Console.

main.py строит config/storage/runtime, регистрирует модули и вызывает runtime.run().
HTTP (FastAPI/uvicorn) полностью в модуле api; Runtime только вызывает api.run_http() после start().
"""

import asyncio
import os
from pathlib import Path

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

from core.config import Config
from core.runtime import CoreRuntime
from core.adapters.storage_factory import build_storage_stack
from core.runtime.module_manager import ModuleSpec
from core.state_engine import StateEngine


APP_MODULES: list[ModuleSpec] = [
    ModuleSpec("logger", required=True),
    ModuleSpec("request_logger", required=True),
    ModuleSpec("api", required=True),
    ModuleSpec("admin", required=True),
    ModuleSpec("auth", required=True),
    ModuleSpec("operations", required=True),
    ModuleSpec("agent", required=False),
    ModuleSpec("credentials", required=False),
    ModuleSpec("execution", required=True),
    ModuleSpec("integrations", required=True),
    ModuleSpec("devices", required=True),
    ModuleSpec("automation", required=False),
    ModuleSpec("presence", required=True),
    ModuleSpec("product_api", required=False),
]


def _parse_module_specs(config: Config) -> list[ModuleSpec]:
    """
    Получить список модулей из config/modules env.

    Формат `RUNTIME_MODULES`:
    - `api,admin,agent`
    - `api:true,admin:true,agent:false`
    """
    raw = getattr(config, "modules_config", None)
    if not raw:
        return APP_MODULES

    specs: list[ModuleSpec] = []
    for item in raw.split(","):
        token = item.strip()
        if not token:
            continue
        if ":" in token:
            name, _, required_raw = token.partition(":")
            required = required_raw.strip().lower() not in ("false", "0", "no", "optional")
            specs.append(ModuleSpec(name.strip(), required=required))
        else:
            specs.append(ModuleSpec(token, required=True))
    return specs or APP_MODULES


async def main() -> None:
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
    runtime = CoreRuntime(
        storage_port=storage_stack.core_port,
        config=config,
        vault_port=storage_stack.vault_port,
        state_engine=state_engine,
    )
    runtime.storage_manager = storage_stack.manager

    # SecretStore для inspector (debug) и credentials: один раз при старте
    try:
        from core.security import SecretStore, SecretStoreStorageAdapter
        backend = storage_stack.manager.get_vault() if storage_stack.manager.is_dual_mode else storage_stack.manager.get_core()
        wrapper = SecretStoreStorageAdapter(backend)
        secret_store = SecretStore(wrapper)
        passphrase = os.getenv("AGENT_SECRET_STORE_PASSPHRASE", "default-dev-passphrase")
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
        print(f"[Runtime] SecretStore not available: {e}")

    print(f"[Runtime] Storage mode: {config.storage_mode} ({config.storage_type})")
    if config.storage_mode == "dual":
        print(f"[Runtime] Vault storage: {config.vault_storage_type}")
    print("[Runtime] Регистрация модулей...")
    module_specs = _parse_module_specs(config)
    await runtime.module_manager.register_module_specs(runtime, module_specs)
    try:
        modules = runtime.module_manager.list_modules()
        if modules:
            print(f"[Runtime] Модули: {modules}")
    except Exception:
        pass

    await runtime.run()

    try:
        await storage_stack.manager.close()
        print("[Runtime] Storage закрыт")
    except Exception:
        pass
    os._exit(0)


if __name__ == "__main__":
    asyncio.run(main())
