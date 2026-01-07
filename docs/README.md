# Core Runtime Service

**Минимальный координатор для plugin-first платформы умного дома (Home Console).**

ЭТО НЕ backend-приложение.  
ЭТО НЕ CRUD.  
ЭТО НЕ FastAPI-сервис.  
**ЭТО RUNTIME / KERNEL.**

> **📚 Навигация:** [INDEX.md](INDEX.md) — полный индекс документации

---

## Философия

Core Runtime — это инфраструктура, которая:
- **стабильна** — минимум изменений, максимум надёжности
- **предсказуема** — простое поведение, явные контракты
- **минимальна** — ничего лишнего, только координация

**Если функциональность можно вынести в плагин — она НЕ должна быть в Core.**

---

## Архитектура

### Основные компоненты

#### 1. **EventBus**
Простая шина событий для обмена сообщениями между плагинами.

```python
# Подписка на событие
event_bus.subscribe("device.state_changed", handler)

# Публикация события
await event_bus.publish("device.state_changed", {
    "device_id": "lamp_kitchen",
    "state": "on"
})
```

#### 2. **ServiceRegistry**
Реестр сервисов для вызова методов плагинов.

```python
# Регистрация сервиса
service_registry.register("devices.turn_on", turn_on_device)

# Вызов сервиса
await service_registry.call("devices.turn_on", "lamp_kitchen")
```

#### 3. **StateEngine**
In-memory хранилище для состояния runtime (НЕ для бизнес-данных).

```python
# Установить значение
await state_engine.set("plugin.status", "running")

# Получить значение
status = await state_engine.get("plugin.status")
```

#### 4. **Storage API**
Единственный способ работы с БД: `namespace + key + JSON value`.

```python
# Сохранить данные
await storage.set("devices", "lamp_kitchen", {
    "state": "on",
    "brightness": 100
})

# Получить данные
data = await storage.get("devices", "lamp_kitchen")
```

**ЗАПРЕЩЕНО:**
- Прямой доступ к БД из плагинов
- ORM (SQLAlchemy, Django ORM)
- Доменные модели
- SQL-запросы из плагинов

#### 5. **PluginManager**
Управление lifecycle плагинов.

```python
# Загрузить плагин
await plugin_manager.load_plugin(my_plugin)

# Запустить плагин
await plugin_manager.start_plugin("my_plugin")

# Остановить плагин
await plugin_manager.stop_plugin("my_plugin")
```

---

## Структура проекта

```
core-runtime-service/
├── main.py                      # Точка входа
├── config.py                    # Конфигурация
├── core/                        # Ядро Runtime
│   ├── runtime.py              # Главный класс CoreRuntime
│   ├── event_bus.py            # Шина событий
│   ├── service_registry.py     # Реестр сервисов
│   ├── state_engine.py         # Управление состоянием
│   ├── storage.py              # Storage API
│   └── plugin_manager.py       # Менеджер плагинов
├── adapters/                    # Адаптеры для внешних систем
│   ├── storage_adapter.py      # Абстрактный интерфейс
│   └── sqlite_adapter.py       # SQLite реализация
└── plugins/                     # Плагины
    ├── base_plugin.py          # Базовый класс плагина
    └── example_plugin.py       # Пример плагина
```

---

## Создание плагина

### 1. Создать класс плагина

```python
from plugins.base_plugin import BasePlugin, PluginMetadata

class MyPlugin(BasePlugin):
    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="my_plugin",
            version="1.0.0",
            description="Описание плагина"
        )
    
    async def on_load(self) -> None:
        """Загрузка: регистрация сервисов, подписка на события."""
        await super().on_load()
        
        # Регистрируем сервис
        self.runtime.service_registry.register(
            "my_plugin.do_something",
            self._do_something
        )
        
        # Подписываемся на события
        self.runtime.event_bus.subscribe(
            "some.event",
            self._on_event
        )
    
    async def on_start(self) -> None:
        """Запуск: старт фоновых задач."""
        await super().on_start()
        # Запустить задачи...
    
    async def on_stop(self) -> None:
        """Остановка: остановить задачи."""
        await super().on_stop()
        # Остановить задачи...
    
    async def on_unload(self) -> None:
        """Выгрузка: отписаться, удалить сервисы."""
        await super().on_unload()
        
        self.runtime.service_registry.unregister("my_plugin.do_something")
        self.runtime.event_bus.unsubscribe("some.event", self._on_event)
    
    async def _do_something(self, arg: str) -> str:
        """Метод сервиса."""
        return f"Обработано: {arg}"
    
    async def _on_event(self, event_type: str, data: dict) -> None:
        """Обработчик события."""
        print(f"Событие {event_type}: {data}")
```

### 2. Зарегистрировать плагин

```python
# В main.py
from plugins.my_plugin import MyPlugin

# Создать и загрузить плагин
plugin = MyPlugin(runtime)
await runtime.plugin_manager.load_plugin(plugin)
await runtime.plugin_manager.start_plugin("my_plugin")
```

---

## Lifecycle плагина

```
UNLOADED → LOADED → STARTED → STOPPED → UNLOADED
            ↑          ↑         ↓
        on_load   on_start   on_stop
                              on_unload
```

**Методы:**
1. `on_load()` — регистрация сервисов, подписка на события
2. `on_start()` — запуск фоновых задач
3. `on_stop()` — остановка задач
4. `on_unload()` — отписка, удаление сервисов

---

## Запуск

```bash
python main.py
```

**Переменные окружения:**
- `RUNTIME_DB_PATH` — путь к БД (по умолчанию: `data/runtime.db`)
- `RUNTIME_SHUTDOWN_TIMEOUT` — таймаут остановки в секундах (по умолчанию: `10`)

---

## Что ЗАПРЕЩЕНО в Core Runtime

- ❌ ORM (SQLAlchemy, Django ORM)
- ❌ Доменные модели
- ❌ Знание таблиц предметной области
- ❌ CRUD-роуты
- ❌ FastAPI
- ❌ Импорт SDK
- ❌ Прямой доступ к БД из плагинов
- ❌ Бизнес-логика

---

## Принципы

1. **МИНИМУМ** — ядро должно быть максимально простым
2. **КООРДИНАЦИЯ** — ядро только координирует, не реализует бизнес-логику
3. **PLUGIN-FIRST** — все домены (devices, users, auth) — это плагины
4. **NO SHARED MEMORY** — плагины не знают друг о друге напрямую
5. **КОНТРАКТЫ** — EventBus и ServiceRegistry — единственные каналы связи

---

## Пример использования

```python
from core.config import Config
from core.runtime import CoreRuntime
from adapters.sqlite_adapter import SQLiteAdapter
from plugins.example_plugin import ExamplePlugin

# Создать Runtime
config = Config.from_env()
adapter = SQLiteAdapter(config.db_path)
runtime = CoreRuntime(adapter)

# Загрузить плагин
plugin = ExamplePlugin(runtime)
await runtime.plugin_manager.load_plugin(plugin)

# Запустить Runtime
await runtime.start()

# Вызвать сервис плагина
result = await runtime.service_registry.call("example.hello", "Мир")
print(result)  # "Привет, Мир!"

# Опубликовать событие
await runtime.event_bus.publish("example.test", {"data": "test"})

# Остановить Runtime
await runtime.shutdown()
```

---

## Remote Plugins

Архитектура позволяет:
- **in-process плагины** — загружаются в тот же процесс
- **remote плагины** — работают через сеть (будущая функциональность)

Контракты:
- Никакого shared memory
- Никаких прямых DB-коннектов
- Только EventBus + ServiceRegistry + Storage API

---

## Лицензия

Этот проект создан для платформы Home Console.
