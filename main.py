"""
Точка входа в приложение Home Console.

Core Runtime (kernel) не знает, какие модули загружать.
Приложение задаёт набор модулей через ApplicationBootstrap (app/bootstrap.py).

Storage Support:
- Single Mode (default): RUNTIME_STORAGE_MODE=single
  One storage adapter handles all namespaces
  
- Dual Mode: RUNTIME_STORAGE_MODE=dual
  Separate core and vault storage with namespace enforcement
  Requires: RUNTIME_VAULT_STORAGE_TYPE and RUNTIME_VAULT_DB_PATH/DSN
"""

import asyncio
import os
import signal
from pathlib import Path

from core.config import Config
from core.runtime import CoreRuntime
from core.storage_factory import create_storage_manager
from app.bootstrap import ApplicationBootstrap, APP_MODULES


async def main():
    """Главная функция запуска приложения."""
    config = Config.from_env()

    # Create directories for storage
    if config.storage_type == "sqlite":
        Path(config.db_path).parent.mkdir(parents=True, exist_ok=True)
    
    if config.storage_mode == "dual" and config.vault_storage_type == "sqlite":
        Path(config.vault_db_path).parent.mkdir(parents=True, exist_ok=True)

    # Create storage manager (handles both single and dual mode)
    storage_manager = await create_storage_manager(config)
    
    # For compatibility with existing CoreRuntime, pass core storage adapter
    # In dual mode, CoreRuntime uses core storage; vault is handled separately
    core_storage = storage_manager.get_core()
    
    runtime = CoreRuntime(core_storage, config=config)
    bootstrap = ApplicationBootstrap(APP_MODULES)

    loop = asyncio.get_running_loop()
    sigint_count = 0
    shutting_down = False

    async def _graceful_shutdown() -> None:
        nonlocal shutting_down
        if shutting_down:
            return
        shutting_down = True
        print("[Runtime] Остановка Core Runtime...")
        try:
            await asyncio.wait_for(
                runtime.shutdown(),
                timeout=config.shutdown_timeout,
            )
            print("[Runtime] Core Runtime остановлен")
            
            # Close storage manager
            await storage_manager.close()
            print("[Runtime] Storage закрыт")
        except asyncio.TimeoutError:
            print("[Runtime] Таймаут при остановке Runtime")
        finally:
            # Гарантированно завершаем процесс после shutdown
            os._exit(0)

    def _handle_sigint(signum, frame):
        nonlocal sigint_count
        sigint_count += 1
        if sigint_count == 1:
            # Первый Ctrl+C — запускаем асинхронный graceful shutdown
            print("\n[Runtime] Получен сигнал остановки (Ctrl+C). Завершаем работу...")
            loop.call_soon_threadsafe(lambda: asyncio.create_task(_graceful_shutdown()))
        else:
            # Повторный Ctrl+C — принудительный выход, без ожидания
            print("\n[Runtime] Повторный Ctrl+C — принудительный выход.")
            os._exit(1)

    # Регистрируем обработчик SIGINT (Ctrl+C)
    signal.signal(signal.SIGINT, _handle_sigint)

    # Log storage mode
    print(f"[Runtime] Storage mode: {config.storage_mode} ({config.storage_type})")
    if config.storage_mode == "dual":
        print(f"[Runtime] Vault storage: {config.vault_storage_type}")

    # 1) Приложение регистрирует модули в Core
    print("[Runtime] Регистрация модулей приложения...")
    await bootstrap.start(runtime)
    try:
        modules = runtime.module_manager.list_modules()
        if modules:
            print(f"[Runtime] Модули зарегистрированы: {modules}")
    except Exception:
        pass

    # 2) Core запускает зарегистрированные модули и плагины (kernel)
    print("[Runtime] Запуск Core Runtime...")
    await runtime.start()
    print("[Runtime] Core Runtime запущен")
    
    # Ждём, пока процесс не будет завершён через Ctrl+C / SIGINT
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
