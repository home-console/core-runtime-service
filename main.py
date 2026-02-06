"""
Точка входа в приложение Home Console.

Core Runtime (kernel) не знает, какие модули загружать.
Приложение задаёт набор модулей через ApplicationBootstrap (app/bootstrap.py).
"""

import asyncio
import signal
from pathlib import Path

from core.config import Config
from core.runtime import CoreRuntime
from core.storage_factory import create_storage_adapter
from app.bootstrap import ApplicationBootstrap, APP_MODULES


async def main():
    """Главная функция запуска приложения."""
    config = Config.from_env()

    if config.storage_type == "sqlite":
        Path(config.db_path).parent.mkdir(parents=True, exist_ok=True)

    storage_adapter = await create_storage_adapter(config)
    runtime = CoreRuntime(storage_adapter, config=config)
    bootstrap = ApplicationBootstrap(APP_MODULES)

    shutdown_event = asyncio.Event()

    def signal_handler():
        print("\n[Runtime] Получен сигнал остановки...")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)

    try:
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

        await shutdown_event.wait()

    finally:
        print("[Runtime] Остановка Core Runtime...")
        try:
            await asyncio.wait_for(
                runtime.shutdown(),
                timeout=config.shutdown_timeout
            )
            print("[Runtime] Core Runtime остановлен")
        except asyncio.TimeoutError:
            print("[Runtime] Таймаут при остановке Runtime")


if __name__ == "__main__":
    asyncio.run(main())
