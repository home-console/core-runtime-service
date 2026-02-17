"""
Точка входа в приложение Home Console.

Core Runtime (kernel) не знает, какие модули загружать.
Приложение задаёт набор модулей через ApplicationBootstrap (app/bootstrap.py).
"""

import asyncio
import os
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
