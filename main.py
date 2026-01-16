"""
Точка входа в Core Runtime.

Минимальный main для запуска runtime.
"""

import asyncio
import signal
from pathlib import Path

from core.config import Config
from core.runtime import CoreRuntime
from core.storage_factory import create_storage_adapter


async def main():
    """Главная функция запуска Core Runtime."""
    
    # Загрузить конфигурацию
    config = Config.from_env()
    
    # Создать директорию для БД, если нужно (только для SQLite)
    if config.storage_type == "sqlite":
        Path(config.db_path).parent.mkdir(parents=True, exist_ok=True)
    
    # Создать storage адаптер на основе конфигурации
    storage_adapter = await create_storage_adapter(config)
    
    # Создать Core Runtime
    # Модули (devices, automation, presence) регистрируются автоматически в CoreRuntime.__init__
    # Передаём config для поддержки shutdown_timeout
    runtime = CoreRuntime(storage_adapter, config=config)
    
    # Диагностика: показать, какие модули и плагины зарегистрированы
    try:
        modules = runtime.module_manager.list_modules()
        if modules:
            print(f"[Runtime] Модули зарегистрированы: {modules}")
    except Exception:
        pass
    
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
