"""
Точка входа в Core Runtime.

Минимальный main для запуска runtime.
"""

import asyncio
import signal
import importlib
import inspect
import pkgutil
from pathlib import Path

from config import Config
from core.runtime import CoreRuntime
from adapters.sqlite_adapter import SQLiteAdapter
from plugins.base_plugin import BasePlugin


async def main():
    """Главная функция запуска Core Runtime."""
    
    # Загрузить конфигурацию
    config = Config.from_env()
    
    # Создать директорию для БД, если нужно
    Path(config.db_path).parent.mkdir(parents=True, exist_ok=True)
    
    # Создать storage адаптер
    storage_adapter = SQLiteAdapter(config.db_path)
    # Явная инициализация схемы (adapter не создаёт схему автоматически)
    await storage_adapter.initialize_schema()
    
    # Создать Core Runtime
    runtime = CoreRuntime(storage_adapter)

    # Автозагрузка плагинов из каталога plugins/
    plugins_dir = Path(__file__).parent / "plugins"
    if plugins_dir.exists() and plugins_dir.is_dir():
        for _finder, mod_name, _ispkg in pkgutil.iter_modules([str(plugins_dir)]):
            module_name = f"plugins.{mod_name}"
            try:
                module = importlib.import_module(module_name)
                for _name, obj in inspect.getmembers(module, inspect.isclass):
                    try:
                        if issubclass(obj, BasePlugin) and obj is not BasePlugin:
                            plugin_instance = obj(runtime)
                            await runtime.plugin_manager.load_plugin(plugin_instance)
                    except Exception:
                        # ignore non-plugin classes or instantiation errors per-class
                        continue
            except Exception as e:
                print(f"[Runtime] Ошибка при импортe плагина {module_name}: {e}")
    # Диагностика: показать, какие плагины загружены
    try:
        loaded = runtime.plugin_manager.list_plugins()
        print(f"[Runtime] Плагины загружены: {loaded}")
    except Exception:
        print("[Runtime] Не удалось получить список загруженных плагинов")
    
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
