"""
Пример использования Core Runtime.

Демонстрирует базовую работу с Runtime и плагинами.
"""

import asyncio
from pathlib import Path

from core.config import Config
from core.runtime import CoreRuntime
from adapters.sqlite_adapter import SQLiteAdapter
from plugins.example_plugin import ExamplePlugin
from plugins.devices_plugin import DevicesPlugin
from plugins.system_logger_plugin import SystemLoggerPlugin
from plugins.automation_stub_plugin import AutomationStubPlugin
try:
    from plugins.api_gateway_plugin import ApiGatewayPlugin
    _HAS_API_GATEWAY = True
except Exception:
    # Если в окружении отсутствуют зависимости fastapi/uvicorn,
    # позволяем демо работать без запуска api_gateway.
    ApiGatewayPlugin = None  # type: ignore
    _HAS_API_GATEWAY = False


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
    
    # 2. Загрузка плагинов
    print("\n[2] Загрузка плагинов...")
    
    # System logger — инфраструктурный плагин
    logger = SystemLoggerPlugin(runtime)
    await runtime.plugin_manager.load_plugin(logger)
    print(f"✓ Плагин '{logger.metadata.name}' загружен")
    
    # Devices — доменный плагин
    devices = DevicesPlugin(runtime)
    await runtime.plugin_manager.load_plugin(devices)
    print(f"✓ Плагин '{devices.metadata.name}' загружен")
    
    # Automation stub — демонстрация event-driven архитектуры
    automation = AutomationStubPlugin(runtime)
    await runtime.plugin_manager.load_plugin(automation)
    print(f"✓ Плагин '{automation.metadata.name}' загружен")

    # Загружаем примерный плагин example, чтобы его сервисы были доступны
    try:
        example = ExamplePlugin(runtime)
        await runtime.plugin_manager.load_plugin(example)
        print(f"✓ Плагин '{example.metadata.name}' загружен")
    except Exception:
        print("! Не удалось загрузить 'example' плагин")

    if _HAS_API_GATEWAY and ApiGatewayPlugin is not None:
        api = ApiGatewayPlugin(runtime)
        await runtime.plugin_manager.load_plugin(api)
        print(f"✓ Плагин '{api.metadata.name}' загружен")
    else:
        print("! Плагин 'api_gateway' пропущен (fastapi/uvicorn не установлены)")
    
    # 3. Запуск Runtime
    print("\n[3] Запуск Runtime...")
    await runtime.start()
    print("✓ Runtime запущен")

    # Печать зарегистрированных HTTP endpoint'ов
    print("\n[3.1] HTTP endpoints:")
    for ep in runtime.http.list():
        print(f"   {ep.method} {ep.path} -> {ep.service}")
    
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
    
    # 6.1. ДЕМОНСТРАЦИЯ EVENT-DRIVEN АВТОМАТИЗАЦИИ
    print("\n[6.1] Демонстрация Event-Driven автоматизации...")
    print("       Создаём устройство и включаем его...")
    
    # Создаём устройство
    new_device = await runtime.service_registry.call(
        "devices.create",
        device_id="lamp_kitchen",
        name="Лампа на кухне",
        device_type="light"
    )
    print(f"       ✓ Создано устройство: {new_device['id']}")
    
    # Включаем устройство — это вызовет событие devices.state_changed
    print("       Включаем устройство...")
    await runtime.service_registry.call("devices.turn_on", "lamp_kitchen")
    print("       ✓ Устройство включено")
    
    # Даём время на обработку события и логирование
    await asyncio.sleep(0.2)
    
    print("       ↓ Цепочка обработки:")
    print("       1. devices.turn_on → изменение состояния")
    print("       2. devices.state_changed → событие")
    print("       3. automation_stub → подписка на событие")
    print("       4. logger.log → сервис системного логирования")
    print("       (см. логи выше — должна быть запись об включении)")
    
    # 6.2. Проверка состояния устройства
    print("\n[6.2] Состояние устройства после автоматизации...")
    lamp = await runtime.service_registry.call("devices.get", "lamp_kitchen")
    print(f"       Текущее состояние: {lamp['state']}")
    
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
