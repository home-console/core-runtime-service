# Быстрый старт

## Установка

```bash
# Клонировать репозиторий
git clone <repository-url>
cd core-runtime-service

# Создать виртуальное окружение (опционально)
python3 -m venv venv
source venv/bin/activate  # Linux/macOS
# или
venv\Scripts\activate  # Windows

# Установить зависимости (минимальны)
pip install -r requirements.txt
```

## Запуск демо

```bash
python3 demo.py
```

Вы увидите полную демонстрацию работы Core Runtime:
- Создание и запуск Runtime
- Загрузка плагина
- Работа с Storage API
- Вызов сервисов
- Публикация событий
- Остановка Runtime

## Запуск Runtime

```bash
python3 main.py
```

Runtime запустится и будет ждать остановки (Ctrl+C).

## Создание своего плагина

### 1. Создайте файл плагина

Создайте `plugins/my_plugin.py`:

```python
from core.base_plugin import BasePlugin, PluginMetadata

class MyPlugin(BasePlugin):
    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="my_plugin",
            version="1.0.0",
            description="Мой первый плагин"
        )
    
    async def on_load(self) -> None:
        await super().on_load()
        print("[MyPlugin] Загружен")
    
    async def on_start(self) -> None:
        await super().on_start()
        print("[MyPlugin] Запущен")
    
    async def on_stop(self) -> None:
        await super().on_stop()
        print("[MyPlugin] Остановлен")
```

### 2. Зарегистрируйте плагин в main.py

```python
from plugins.my_plugin import MyPlugin

# В функции main() после создания runtime:
plugin = MyPlugin(runtime)
await runtime.plugin_manager.load_plugin(plugin)
```

### 3. Запустите

```bash
python3 main.py
```

## Примеры использования

### Storage API

```python
# Сохранить данные
await runtime.storage.set("devices", "lamp_1", {
    "name": "Лампа в спальне",
    "state": "on"
})

# Получить данные
device = await runtime.storage.get("devices", "lamp_1")

# Список ключей
keys = await runtime.storage.list_keys("devices")

# Удалить
await runtime.storage.delete("devices", "lamp_1")
```

### EventBus

```python
# Подписка на событие
async def on_event(event_type: str, data: dict):
    print(f"Событие: {event_type}, данные: {data}")

runtime.event_bus.subscribe("device.changed", on_event)

# Публикация события
await runtime.event_bus.publish("device.changed", {
    "device_id": "lamp_1",
    "state": "off"
})
```

### ServiceRegistry

```python
# Регистрация сервиса
async def turn_on(device_id: str):
    return {"status": "ok", "device_id": device_id}

runtime.service_registry.register("devices.turn_on", turn_on)

# Вызов сервиса
result = await runtime.service_registry.call("devices.turn_on", "lamp_1")
```

### StateEngine

```python
# Установить состояние
await runtime.state_engine.set("system.mode", "normal")

# Получить состояние
mode = await runtime.state_engine.get("system.mode")

# Проверить существование
exists = await runtime.state_engine.exists("system.mode")
```

## Конфигурация

Переменные окружения:

```bash
# Путь к БД (по умолчанию: data/runtime.db)
export RUNTIME_DB_PATH=/path/to/database.db

# Таймаут остановки в секундах (по умолчанию: 10)
export RUNTIME_SHUTDOWN_TIMEOUT=30
```

Или отредактируйте `config.py`:

```python
config = Config(
    db_path="custom/path/db.db",
    shutdown_timeout=20
)
```

## Структура проекта

```
core-runtime-service/
├── main.py              # Точка входа
├── demo.py              # Демонстрация
├── config.py            # Конфигурация
├── core/                # Ядро Runtime
├── adapters/            # Адаптеры (Storage)
└── plugins/             # Плагины
    ├── base_plugin.py   # Базовый класс
    └── test/            # Тестовые плагины
        └── example_plugin.py # Пример
```

## Дальнейшие шаги

1. Изучите [00-README.md](00-README.md) для понимания концепций
2. Изучите [01-ARCHITECTURE.md](01-ARCHITECTURE.md) для деталей архитектуры
3. Посмотрите `plugins/test/example_plugin.py` для примера плагина
4. Создайте свой плагин для вашего домена

## Помощь

Если что-то не работает:
1. Проверьте версию Python (требуется 3.11+)
2. Проверьте логи в терминале
3. Изучите `demo.py` для примеров использования
4. Прочитайте документацию в [00-README.md](00-README.md)

## Что дальше?

Создайте плагины для вашей платформы умного дома:
- `devices` — управление устройствами
- `users` — пользователи и аутентификация
- `automation` — правила автоматизации
- `notifications` — уведомления
- `api_gateway` — HTTP API (если нужно)

Все домены — это плагины! Core Runtime — только координатор.
