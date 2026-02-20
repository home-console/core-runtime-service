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
from adapters.storage_factory import build_storage_stack
from core.module_manager import ModuleSpec
from core.state_engine import StateEngine


APP_MODULES: list[ModuleSpec] = [
    ModuleSpec("logger", required=True),
    ModuleSpec("request_logger", required=True),
    ModuleSpec("api", required=True),
    ModuleSpec("admin", required=True),
    ModuleSpec("auth", required=True),
    ModuleSpec("operations", required=True),
    ModuleSpec("agent", required=False),
    ModuleSpec("execution", required=True),
    ModuleSpec("integrations", required=True),
    ModuleSpec("devices", required=True),
    ModuleSpec("automation", required=False),
    ModuleSpec("presence", required=True),
    ModuleSpec("product_api", required=False),
]


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

    print(f"[Runtime] Storage mode: {config.storage_mode} ({config.storage_type})")
    if config.storage_mode == "dual":
        print(f"[Runtime] Vault storage: {config.vault_storage_type}")
    print("[Runtime] Регистрация модулей...")
    await runtime.module_manager.register_module_specs(runtime, APP_MODULES)
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
