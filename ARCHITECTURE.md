# Архитектура Core Runtime

## Обзор

Core Runtime — это минимальный kernel для plugin-first платформы умного дома.

```
┌─────────────────────────────────────────────────────┐
│                   CORE RUNTIME                      │
│                                                     │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────┐ │
│  │  EventBus   │  │ServiceRegistry│  │StateEngine│ │
│  └─────────────┘  └──────────────┘  └───────────┘ │
│                                                     │
│  ┌─────────────┐  ┌──────────────┐                │
│  │  Storage    │  │PluginManager │                │
│  └─────────────┘  └──────────────┘                │
└─────────────────────────────────────────────────────┘
         ↑              ↑              ↑
         │              │              │
    ┌────┴───┐     ┌────┴───┐     ┌───┴────┐
    │Plugin 1│     │Plugin 2│     │Plugin 3│
    │(devices)│    │(users) │     │(auto)  │
    └────────┘     └────────┘     └────────┘
```

---

## Принципы проектирования

### 1. Минимализм
Ядро содержит ТОЛЬКО координацию, НЕ бизнес-логику.

**Правило:** Если функциональность можно вынести в плагин — она НЕ должна быть в Core.

### 2. Plugin-First
Все домены реализуются как плагины:
- `devices` — управление устройствами
- `users` — пользователи и аутентификация
- `automation` — автоматизация
- `notifications` — уведомления

Core НЕ знает про эти домены.

### 3. Изоляция
Плагины:
- НЕ знают друг о друге
- НЕ имеют прямого доступа к БД
- НЕ используют shared memory

Взаимодействие только через:
- EventBus (pub/sub)
- ServiceRegistry (RPC)
- Storage API (данные)

### 4. Предсказуемость
Простое поведение, явные контракты, минимум магии.

---

## Компоненты

### EventBus

**Назначение:** маршрутизация событий между плагинами.

**Принцип:** pub/sub (publish/subscribe).

```python
# Плагин A публикует событие
await event_bus.publish("device.state_changed", {
    "device_id": "lamp_1",
    "state": "on"
})

# Плагин B подписывается на событие
async def on_device_changed(event_type: str, data: dict):
    print(f"Устройство {data['device_id']} изменилось")

event_bus.subscribe("device.state_changed", on_device_changed)
```

**Гарантии:**
- Асинхронная доставка
- Все подписчики получают событие
- Ошибка в одном подписчике НЕ влияет на других

**НЕ гарантируется:**
- Порядок доставки
- Повторная доставка при ошибке

---

### ServiceRegistry

**Назначение:** вызов методов между плагинами.

**Принцип:** RPC (Remote Procedure Call).

```python
# Плагин A регистрирует сервис
async def turn_on_device(device_id: str):
    # логика включения
    return {"status": "ok"}

service_registry.register("devices.turn_on", turn_on_device)

# Плагин B вызывает сервис
result = await service_registry.call("devices.turn_on", "lamp_1")
```

**Особенности:**
- Синхронный вызов (с await)
- Возвращает результат
- Выбрасывает исключение при ошибке
- Один сервис = одна функция

---

### StateEngine

**Назначение:** хранение общего состояния Runtime.

**Для чего:**
- Статус плагинов
- Флаги состояния системы
- Временные данные для координации

**Для чего НЕ:**
- Бизнес-данные (используй Storage API)
- Персистентные данные (используй Storage API)

```python
# Установить состояние
await state_engine.set("system.maintenance_mode", True)

# Получить состояние
maintenance = await state_engine.get("system.maintenance_mode")
```

**Особенности:**
- In-memory (не персистентное)
- Thread-safe (с async lock)
- Может хранить любые типы Python

---

### Storage API

**Назначение:** единственный способ работы с БД.

**Модель:** `namespace + key + JSON value`

```python
# Сохранить данные
await storage.set("devices", "lamp_1", {
    "name": "Лампа в спальне",
    "state": "off",
    "brightness": 0
})

# Получить данные
device = await storage.get("devices", "lamp_1")

# Список ключей в namespace
keys = await storage.list_keys("devices")

# Удалить данные
await storage.delete("devices", "lamp_1")
```

**ЗАПРЕЩЕНО:**
- Прямой доступ к БД из плагинов
- ORM модели
- SQL-запросы
- Транзакции (пока)

**Реализация:**
- Абстрактный интерфейс `StorageAdapter`
- Конкретная реализация `SQLiteAdapter`
- Легко добавить PostgreSQL, Redis, etc.

---

### PluginManager

**Назначение:** управление lifecycle плагинов.

**Lifecycle:**
```
UNLOADED → LOADED → STARTED → STOPPED → UNLOADED
```

**Методы:**
- `load_plugin()` — загрузить плагин
- `start_plugin()` — запустить плагин
- `stop_plugin()` — остановить плагин
- `unload_plugin()` — выгрузить плагин
- `start_all()` — запустить все плагины
- `stop_all()` — остановить все плагины

**Зависимости:**
```python
PluginMetadata(
    name="automation",
    dependencies=["devices", "users"]  # Требует другие плагины
)
```

---

## Архитектурные решения

### Почему НЕ FastAPI?

FastAPI — для HTTP API.  
Core Runtime — kernel, не веб-сервис.

Если нужен HTTP API — создай плагин `api_gateway`.

### Почему НЕ ORM?

ORM привязывает к схеме БД.  
Storage API — key-value, без схемы.

Плагины НЕ должны знать структуру БД.

### Почему async?

- Плагины могут быть I/O-bound
- EventBus требует асинхронности
- Удобно для фоновых задач

### Почему одна таблица для Storage?

Простота, гибкость, независимость от домена.

Если нужны сложные запросы — создай плагин с индексами поверх Storage API.

---

## Паттерны использования

### Паттерн: Event Sourcing

```python
# Плагин публикует события изменений
await event_bus.publish("device.state_changed", {
    "device_id": "lamp_1",
    "old_state": "off",
    "new_state": "on",
    "timestamp": "2026-01-06T12:00:00Z"
})

# Другие плагины реагируют на события
# Например, плагин аналитики сохраняет историю
```

### Паттерн: Service Composition

```python
# Плагин A предоставляет базовый сервис
service_registry.register("devices.turn_on", turn_on_device)

# Плагин B использует сервис A
async def turn_on_room(room_id: str):
    devices = await get_room_devices(room_id)
    for device in devices:
        await service_registry.call("devices.turn_on", device["id"])
```

### Паттерн: State Machine

```python
# Используем StateEngine для отслеживания состояний
await state_engine.set("system.mode", "normal")

# Плагины проверяют состояние перед действием
mode = await state_engine.get("system.mode")
if mode == "maintenance":
    return  # Не выполнять действие
```

---

## Remote Plugins (будущее)

### Цель
Поддержка плагинов, работающих в отдельных процессах/на других машинах.

### Архитектура
```
┌───────────────┐         ┌──────────────┐
│ Core Runtime  │ ←────→  │ Remote Plugin│
│               │  gRPC   │   (Process)  │
└───────────────┘         └──────────────┘
```

### Контракты
- EventBus → gRPC stream
- ServiceRegistry → gRPC unary call
- Storage API → gRPC unary call

### Требования
- Никаких shared memory
- Никаких прямых DB-коннектов
- Сериализация всех данных

---

## Расширяемость

### Добавить новый Storage адаптер

```python
from adapters.storage_adapter import StorageAdapter

class RedisAdapter(StorageAdapter):
    async def get(self, namespace: str, key: str):
        # Реализация для Redis
        pass
    
    # ... остальные методы
```

### Добавить мониторинг

Создай плагин `monitoring`:
- Подписывается на все события
- Собирает метрики
- Отправляет в систему мониторинга

### Добавить HTTP API

Создай плагин `api_gateway`:
- Поднимает FastAPI
- Вызывает сервисы через ServiceRegistry
- Публикует события через EventBus

---

## Ограничения

### Текущие
- Нет транзакций в Storage API
- Нет распределённых событий
- Нет персистентности EventBus
- Нет rate limiting

### Намеренные
- Нет ORM (используй Storage API)
- Нет HTTP в ядре (создай плагин)
- Нет бизнес-логики в Core
- Нет прямого доступа к БД

---

## Безопасность

### Изоляция плагинов
Плагины работают в одном процессе → нет полной изоляции.

Для критичных плагинов используй Remote Plugins.

### Валидация данных
Core Runtime НЕ валидирует данные плагинов.

Плагины сами отвечают за валидацию.

### Аутентификация
Нет встроенной аутентификации.

Создай плагин `auth` для этого.

---

## Производительность

### EventBus
- O(n) где n = количество подписчиков
- Параллельная обработка всех подписчиков
- Не блокирует publisher

### ServiceRegistry
- O(1) поиск сервиса
- Синхронный вызов
- Может быть bottleneck

### Storage API
- Зависит от адаптера
- SQLite: O(log n) для индексированных полей
- Нет кэширования (добавь через плагин)

### StateEngine
- O(1) операции (dict lookup)
- In-memory, очень быстро
- Требует lock для thread-safety

---

## Тестирование

### Юнит-тесты компонентов

```python
import pytest
from core.event_bus import EventBus

@pytest.mark.asyncio
async def test_event_bus():
    bus = EventBus()
    received = []
    
    async def handler(event_type, data):
        received.append(data)
    
    bus.subscribe("test", handler)
    await bus.publish("test", {"value": 42})
    
    assert len(received) == 1
    assert received[0]["value"] == 42
```

### Интеграционные тесты с плагинами

```python
@pytest.mark.asyncio
async def test_plugin_lifecycle():
    runtime = CoreRuntime(MemoryStorageAdapter())
    plugin = ExamplePlugin(runtime)
    
    await runtime.plugin_manager.load_plugin(plugin)
    assert plugin.is_loaded
    
    await runtime.plugin_manager.start_plugin("example")
    assert plugin.is_started
    
    await runtime.plugin_manager.stop_plugin("example")
    assert not plugin.is_started
```

---

## Заключение

Core Runtime — это **kernel**, а не **application**.

Он должен быть:
- Минимальным
- Стабильным
- Предсказуемым

Вся бизнес-логика — в плагинах.
