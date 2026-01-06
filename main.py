"""
Точка входа в Core Runtime.

Минимальный main для запуска runtime.
"""

import asyncio
import signal
from pathlib import Path

from config import Config
from core.runtime import CoreRuntime
from adapters.sqlite_adapter import SQLiteAdapter


async def main():
    """Главная функция запуска Core Runtime."""
    
    # Загрузить конфигурацию
    config = Config.from_env()
    
    # Создать директорию для БД, если нужно
    Path(config.db_path).parent.mkdir(parents=True, exist_ok=True)
    
    # Создать storage адаптер
    storage_adapter = SQLiteAdapter(config.db_path)
    
    # Создать Core Runtime
    runtime = CoreRuntime(storage_adapter)
    
    # Обработка сигналов для graceful shutdown
    shutdown_event = asyncio.Event()
    
    def signal_handler():
        """Обработчик сигналов остановки."""
        print("\n[Runtime] Получен сигнал остановки...")
        shutdown_event.set()
    
    # Зарегистрировать обработчики сигналов
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)
    
    try:
        # Запустить Runtime
        print("[Runtime] Запуск Core Runtime...")
        await runtime.start()
        print("[Runtime] Core Runtime запущен")
        
        # Ждать сигнала остановки
        await shutdown_event.wait()
        
    finally:
        # Остановить Runtime
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
