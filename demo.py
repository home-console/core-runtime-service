"""
Пример использования Core Runtime.

Демонстрирует базовую работу с Runtime и плагинами.
"""

import asyncio
from pathlib import Path

from config import Config
from core.runtime import CoreRuntime
from adapters.sqlite_adapter import SQLiteAdapter
from plugins.example_plugin import ExamplePlugin


async def demo():
    """Демонстрация работы Core Runtime."""
    
    print("=" * 60)
    print("ДЕМОНСТРАЦИЯ CORE RUNTIME")
    print("=" * 60)
    
    # 1. Создание Runtime
    print("\n[1] Создание Runtime...")
    config = Config(db_path="data/demo.db")
    Path(config.db_path).parent.mkdir(parents=True, exist_ok=True)
    
    adapter = SQLiteAdapter(config.db_path)
    # Инициализация схемы для demo
    await adapter.initialize_schema()
    runtime = CoreRuntime(adapter)
    print("✓ Runtime создан")
    
    # 2. Загрузка плагина
    print("\n[2] Загрузка плагина...")
    plugin = ExamplePlugin(runtime)
    await runtime.plugin_manager.load_plugin(plugin)
    print(f"✓ Плагин '{plugin.metadata.name}' загружен")
    
    # 3. Запуск Runtime
    print("\n[3] Запуск Runtime...")
    await runtime.start()
    print("✓ Runtime запущен")
    
    # 4. Проверка Storage
    print("\n[4] Проверка Storage API...")
    status = await runtime.storage.get("example", "status")
    print(f"   Статус плагина: {status}")
    
    # 5. Вызов сервиса
    print("\n[5] Вызов сервиса плагина...")
    result = await runtime.service_registry.call("example.hello", "Разработчик")
    print(f"   Результат: {result}")
    
    # 6. Публикация события
    print("\n[6] Публикация события...")
    await runtime.event_bus.publish("example.test", {
        "message": "Это тестовое событие",
        "timestamp": "2026-01-06"
    })
    await asyncio.sleep(0.1)  # Дать время на обработку
    
    # 7. Проверка состояния
    print("\n[7] Проверка состояния Runtime...")
    runtime_status = await runtime.state_engine.get("runtime.status")
    print(f"   Статус Runtime: {runtime_status}")
    
    # 8. Работа с Storage
    print("\n[8] Сохранение данных в Storage...")
    await runtime.storage.set("demo", "device_1", {
        "name": "Лампа в кухне",
        "state": "on",
        "brightness": 75
    })
    
    keys = await runtime.storage.list_keys("demo")
    print(f"   Ключи в namespace 'demo': {keys}")
    
    device = await runtime.storage.get("demo", "device_1")
    print(f"   Устройство: {device}")
    
    # 9. Список плагинов
    print("\n[9] Список загруженных плагинов...")
    plugins = runtime.plugin_manager.list_plugins()
    print(f"   Плагины: {plugins}")
    
    for plugin_name in plugins:
        state = runtime.plugin_manager.get_plugin_state(plugin_name)
        if state is None:
            state_repr = "None"
        else:
            state_repr = getattr(state, "value", str(state))
        print(f"   - {plugin_name}: {state_repr}")
    
    # 10. Остановка Runtime
    print("\n[10] Остановка Runtime...")
    await runtime.shutdown()
    print("✓ Runtime остановлен")
    
    print("\n" + "=" * 60)
    print("ДЕМОНСТРАЦИЯ ЗАВЕРШЕНА")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(demo())
