# Архитектура Core Runtime

> **Статус документа:** Stable  
> **Версия:** 0.2.0  
> **Последнее изменение:** 2026-01-09  
> **Следующий ревью:** 2026-02-01

---

## Статус этого документа

Этот документ является **источником истины** для архитектурных решений Core Runtime.

**Что здесь описано:**
- Инварианты архитектуры (неизменяемые правила)
- Контракты между компонентами
- Границы ответственности
- Стабильные и переходные части системы

**Что здесь НЕ описано:**
- Детали реализации (см. код)
- API reference (см. [04-CORE-RUNTIME-CONTRACT.md](04-CORE-RUNTIME-CONTRACT.md))
- Примеры использования (см. [03-QUICKSTART.md](03-QUICKSTART.md))
- Разработка плагинов (см. [02-MODULES-AND-PLUGINS.md](02-MODULES-AND-PLUGINS.md))

---

## Краткое определение

Core Runtime — минимальное «глупое» ядро, обеспечивающее инфраструктуру для плагинов:
- маршрутизация событий (EventBus) — **Stable**
- вызов сервисов между плагинами (ServiceRegistry) — **Stable**
- хранение текущего состояния во времени выполнения (StateEngine) — **Stable**
- абстрактный Storage API — **Stable**
- жизненный цикл плагинов (PluginManager) — **Stable**
- декларативный реестр внешних интерфейсов (HttpRegistry) — **Transitional**

Core не содержит доменной логики; он только предоставляет гарантированный, предсказуемый набор примитивов.

---

## Компоненты и роли

### Core Runtime
Владелец инфраструктуры. Отвечает за надёжность и стабильность API runtime.

**Статус:** Stable

### Module (модуль)
Обязательная доменная логика, регистрируется в CoreRuntime при инициализации. НЕ зависит от PluginManager.

**Статус:** Stable (введено в v0.2.0)

**Примеры:** `modules/devices/` — доменная логика управления устройствами

**Подробнее:** [02-MODULES-AND-PLUGINS.md](02-MODULES-AND-PLUGINS.md)

### Plugin (плагин)
Опциональное расширение, загружаемое через PluginManager. Наследуется от BasePlugin.

**Статус:** Stable

**Примеры:** 
- System plugins: `system_logger`, `api_gateway`
- Integration plugins: `yandex_smart_home_real`, `oauth_yandex`

**Подробнее:** [02-MODULES-AND-PLUGINS.md](02-MODULES-AND-PLUGINS.md)

### Adapter
Транспортная проекция декларативных контрактов (`HttpRegistry`) на конкретный транспорт (HTTP, CLI и т.д.). Адаптеры не владеют бизнес-логикой.

**Статус:** Transitional

**Примеры:**
- HTTP adapter: `api_gateway_plugin` (FastAPI)
- CLI adapter: `console.py`

---

## Plugin — контракт и lifecycle

**Статус:** Stable

Каждый плагин обязан:
- наследоваться от `BasePlugin` и реализовать `metadata`;
- использовать lifecycle: `__init__` → `on_load()` → `on_start()` → `on_stop()` → `on_unload()`;
- взаимодействовать исключительно через: `runtime.service_registry`, `runtime.event_bus`, `runtime.state_engine`, `runtime.storage`, `runtime.http`.

Плагин НЕ должен импортировать или вызывать код других плагинов напрямую.

---

## Adapter — проекция `HttpRegistry`

**Статус:** Transitional (API может измениться)

Источник правды для внешних интерфейсов — `HttpRegistry`.

Адаптер читает декларативные `HttpEndpoint` из `runtime.http.list()` и строит реальные входные точки:
- HTTP adapter (`api_gateway`) регистрирует маршруты в FastAPI по подписанным контрактам;
- CLI adapter (`console.py`) формирует список команд/действий на основе тех же контрактов и выполняет соответствующие сервисы;

Ключевой инвариант: одна декларация интерфейсов → много адаптеров (ONE DECLARATION → MANY ADAPTERS).
Адаптеры не хранят собственный список команд и не дублируют логику `HttpRegistry`.

**Ограничения:**
- HttpRegistry API может измениться в будущих версиях
- Документация по использованию HttpRegistry неполная

---

## Почему Core не знает адаптеры и домены

Разделение ответственности гарантирует простоту ядра и долгую стабильность API. Core предоставляет лишь примитивы (events/services/state), а конкретные точки входа и доменная логика реализуются плагинами и адаптерами.

---

## Инварианты архитектуры (обязательные)

**Статус:** Stable (нарушение этих правил = breaking change)

1. **Core не содержит доменной логики** и не импортирует плагины.
2. **Плагины не импортируют друг друга**; взаимодействие только через runtime API.
3. **Все внешние интерфейсы объявляются декларативно** через `HttpRegistry`; адаптеры используют эту декларацию.
4. **ORM/персистентность не должны быть частью Core** — Core пользуется адаптерами Storage.
5. **Изменения в Core должны быть минимальными**, хорошо аргументированными и сопровождаться миграционным планом.

---

## Что Core запрещено делать

**Статус:** Stable (неизменяемые ограничения)

- Внедрять бизнес-логику или доменные понятия (devices, presence, automation rules).
- Управлять списком плагинов домена напрямую (плагины управляют собой через PluginManager).
- Внедрять ORM или завязываться на конкретную СУБД.

---

## Что плагинам запрещено делать

**Статус:** Stable (неизменяемые ограничения)

- Импортировать или вызывать код других плагинов напрямую.
- Хранить критическую инфраструктуру (заменять Core функции).
- Взаимодействовать с внешними системами без использования адаптеров (например, напрямую запускать HTTP серверы).

---

## Capabilities и вызовы через ServiceRegistry

**Статус:** Stable (CapabilityRegistry — метаданные; вызовы — только через ServiceRegistry/фасад)

### Capability ≠ Plugin

- **Capability** — это обещание наличия поведения, а не способ его вызова.
- **Plugin** может быть: **provider** (предоставляет capability), **consumer** (требует capability), или тем и другим.
- Плагин объявляет в `PluginMetadata`: `capabilities_provided`, `capabilities_required`.
- **CapabilityRegistry** (core) хранит только метаданные: кто какой capability предоставляет и кто какой требует. Нет методов `call` / `resolve` / `invoke`. Вызовы — только через ServiceRegistry (внутри фасада consumer'а).

### Правило: плагину запрещено зависеть от имени другого плагина

- **Плагину ЗАПРЕЩЕНО:**
  - зависеть от имени другого плагина (жёсткая привязка к `oauth_yandex`, `yandex_device_auth` и т.п.);
  - делать `service_registry.call()` к чужому плагину **вне фасада** — все вызовы к capability идут через один фасад внутри плагина.

- **МОЖНО** вызывать через ServiceRegistry:
  - **Инфраструктурные сервисы** (logger.log, request_logger.create_http_session).
  - **Сервисы модулей** (devices.list, devices.get, devices.list_mappings).
  - **Собственные сервисы плагина** (внутри одного плагина).
  - Вызовы к capability — **только из фасада** (фасад внутри consumer'а делегирует в service_registry по известным именам сервисов; замена реализации в будущем — локально в фасаде).

### CapabilityRegistry и старт плагинов

- При загрузке плагина PluginManager регистрирует в CapabilityRegistry: `capabilities_provided`, `capabilities_required`.
- При старте плагина проверяется: все ли требуемые capabilities имеют хотя бы одного provider. Если нет — плагин **не стартует** (состояние остаётся LOADED), причина доступна через `plugin_manager.get_plugin_block_reason(plugin_name)` (например `{"missing_capabilities": ["oauth:yandex"]}`). Это управляемое состояние (misconfigured/blocked), а не исключение рантайма.

### Operations и интеграции (правило)

- **Любая интеграция** (плагин или модуль) **регистрирует свои операции сама** в `on_start()` / `start()` через `runtime.operations.register_handler(op_type, handler)`.
- **Admin** не содержит интеграционной логики: не знает домены (Yandex, devices и т.д.), не регистрирует handlers, не вызывает `service_registry.call("yandex.*")` и т.п. Единственный mutating API для Admin UI — **POST /admin/v1/operations** с `{ "type": "...", "params": {...} }`.
- **Отсутствие плагина = отсутствие операций:** если плагин не загружен, его типы операций не зарегистрированы; POST /admin/v1/operations с таким типом возвращает ошибку (unknown operation). Это ожидаемое поведение.

### Legacy / Transitional

- Прямые вызовы `service_registry.call("oauth_yandex.*")` вне фасада считаются **legacy**.

### Карта capability → provider → consumers

| Capability ID       | Provider (текущий) | Consumers              |
|---------------------|--------------------|------------------------|
| `oauth:yandex`      | oauth_yandex       | yandex_smart_home      |
| `yandex:session_cookies` | oauth_yandex, yandex_device_auth | yandex_smart_home |

Контракты (документация/типизация): `plugins/oauth_yandex/capability.py`, `docs/capabilities/`. Consumer знает capability только по ID (строка); контракты не импортируются из consumer'а.

---

## Inspector

**Статус:** Stable

Inspector — это **read-only способ наблюдать уже существующее состояние runtime**, не влияя на систему и не зная доменов.

**Inspector — это НЕ API, НЕ модуль, НЕ слой бизнес-логики.**

- Inspector ≠ Operations  
- Inspector ≠ Admin logic (мутирующая часть)  
- Inspector ≠ Plugin logic  

Inspector — тупой. И в этом его ценность: он только отражает то, что уже есть.

### Определение

- **Inspector** — зеркало runtime: только читает метаданные и снимки состояния, ничего не меняет и не вызывает доменные сервисы.
- Реализация Inspector-views в коде может называться **Introspection** (например, `modules/admin/introspection.py`). Допустимые термины: Inspector, Snapshot, Runtime View, Introspection. Запрещённые: «read api», «readonly api», «query api».

### Допустимые источники данных Inspector

Inspector **имеет право** читать **только**:

| Источник | Разрешено |
|----------|-----------|
| `runtime.plugin_manager` (list, метаданные) | ✅ |
| `runtime.service_registry.list_services()` | ✅ |
| `runtime.http.list()` | ✅ |
| `runtime.event_bus.list_subscriptions()` | ✅ |
| `runtime.state.list_keys()` / `runtime.state.get(key)` | ✅ |
| `runtime.storage.list_namespaces()` / `runtime.storage.list_keys(ns)` / `runtime.storage.get(ns, key)` | ✅ (read-only) |

Inspector **не имеет права**:

- вызывать `service_registry.call()`;
- создавать или выполнять operations;
- знать о доменах (devices, yandex, integrations) или проверять «если плагин загружен»;
- выполнять бизнес-логику или делать внешний IO.

При отсутствии плагина Inspector просто показывает меньше данных (меньше записей в списках). Без fallback-логики и без проверок имён плагинов.

### Inspector vs Operations

**Правило:** любой endpoint, который **может** изменить систему, **не может** быть Inspector.

| Действие | Где |
|----------|-----|
| Посмотреть plugins, services, http, events | Inspector |
| Посмотреть state, storage (read-only) | Inspector |
| Посмотреть список зарегистрированных интеграций (метаданные) | Inspector |
| Синхронизировать устройства, проверить online, set_state и т.п. | Operation |

Все мутации системы — **только** через Operations (POST /admin/v1/operations). Inspector только читает.

### AdminModule как Control Plane Host + Inspector Host

После рефакторинга AdminModule:

- **не содержит** доменной логики, интеграционной логики, operations handlers;
- **только:** собирает Inspector views (introspection), проксирует operations (POST /admin/v1/operations), auth / ACL / CSRF.

AdminModule = Control Plane Host + Inspector Host. Inspector-часть не вызывает `service_registry.call()`, не знает имён плагинов/интеграций, не содержит `if plugin_loaded`.

### Критерий корректности (Definition of Done)

Система считается корректной, если:

- Inspector endpoints не вызывают `service_registry.call`;
- Inspector не знает ни одного plugin name / integration в логике;
- Inspector не содержит `if plugin_loaded`;
- При отсутствии плагина Inspector просто показывает меньше данных;
- Все мутации системы идут только через Operations.

### UI / CLI / Debug читают только через Inspector

**Правило:** любой UI, CLI или отладочный инструмент читает состояние системы **только** через Inspector (GET /admin/v1/inspector/*). Не через вызовы сервисов (`service_registry.call()` ради чтения), не через доменные API.

- **Inspector** — единственный источник read-only данных о runtime (plugins, services, http, events, state, storage, **available operation types**).
- Доступные операции UI узнаёт из GET /admin/v1/inspector/operations; кнопки действий → POST /admin/v1/operations.
- Если операции нет в списке — кнопки нет. UI не проверяет плагины, не знает домены.

Пути Inspector (read-only): `/admin/v1/inspector/runtime`, `/admin/v1/inspector/plugins`, `/admin/v1/inspector/services`, `/admin/v1/inspector/http`, `/admin/v1/inspector/events`, `/admin/v1/inspector/dashboard`, `/admin/v1/inspector/storage`, `/admin/v1/inspector/state`, `/admin/v1/inspector/state/keys`, `/admin/v1/inspector/state/{key}`, `/admin/v1/inspector/operations`.

---

## Краткая диаграмма взаимодействия

```
           ┌────────────┐        adapter (HTTP/CLI)
   Plugin  │ HttpRegistry│◀───────────────────────────── external
    ↕      └────────────┘
    │            ▲
    │            │
    ▼            │
 ┌────────┐   ┌────────────┐    ┌─────────────┐
 │Plugin A│◀─▶│ Core Runtime│◀─▶│ Plugin B    │
 └────────┘   └────────────┘    └─────────────┘
               (events/services/state)
```

---

## Политика изменения

**Статус:** Stable

Любое изменение в API Core требует:
1. Явной причины и тестового сценария;
2. Наличия минимум двух независимых плагинов, использующих изменяемый контракт;
3. Плана обратной совместимости или миграции.

---

## Принципы проектирования

### 1. Минимализм
Ядро содержит ТОЛЬКО координацию, НЕ бизнес-логику.

**Правило:** Если функциональность можно вынести в плагин — она НЕ должна быть в Core.

**Статус:** Stable

### 2. Plugin-First
Все домены реализуются как плагины или модули:
- **Modules** — обязательная доменная логика (devices, presence)
- **Plugins** — опциональные расширения (интеграции, UI, оркестрация)

Core НЕ знает про эти домены.

**Статус:** Stable

### 3. Изоляция
Плагины:
- НЕ знают друг о друге
- НЕ имеют прямого доступа к БД
- НЕ используют shared memory

Взаимодействие только через:
- EventBus (pub/sub)
- ServiceRegistry (RPC)
- Storage API (данные)

**Статус:** Stable

### 4. Предсказуемость
Простое поведение, явные контракты, минимум магии.

**Статус:** Stable

---

## Компоненты Core Runtime

### EventBus

**Статус:** Stable

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

**Подробнее:** [04-CORE-RUNTIME-CONTRACT.md](04-CORE-RUNTIME-CONTRACT.md)

---

### ServiceRegistry

**Статус:** Stable

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

**Подробнее:** [04-CORE-RUNTIME-CONTRACT.md](04-CORE-RUNTIME-CONTRACT.md)

---

### StateEngine

**Статус:** Stable

**Назначение:** хранение общего состояния Runtime (read-only кеш).

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
- Автоматически синхронизируется с Storage (mirroring)

**Важно:** StateEngine — это кеш, а не источник истины. Источник истины — Storage API.

**Подробнее:** [04-CORE-RUNTIME-CONTRACT.md](04-CORE-RUNTIME-CONTRACT.md)

---

### Storage API

**Статус:** Stable

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

**Storage → StateEngine mirroring:**
При вызове `storage.set(namespace, key, value)` автоматически обновляется `state_engine.set(f"{namespace}.{key}", value)`. Это обеспечивает быстрый доступ к данным через StateEngine без дополнительных запросов к Storage.

**Подробнее:** [04-CORE-RUNTIME-CONTRACT.md](04-CORE-RUNTIME-CONTRACT.md)

---

### PluginManager

**Статус:** Stable

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

### HttpRegistry

**Статус:** Transitional (API может измениться)

**Назначение:** декларативный реестр внешних интерфейсов.

**Принцип:** Плагины объявляют HTTP endpoints декларативно, адаптеры проецируют их на конкретный транспорт.

**Ограничения:**
- Документация неполная
- API может измениться в будущих версиях
- Примеры использования ограничены

**Подробнее:** См. код `core/http_registry.py` и примеры в `plugins/api_gateway_plugin.py`

---

## Архитектурные решения

### Почему НЕ FastAPI?

FastAPI — для HTTP API.  
Core Runtime — kernel, не веб-сервис.

Если нужен HTTP API — создай плагин `api_gateway`.

**Статус:** Stable (неизменяемое решение)

### Почему НЕ ORM?

ORM привязывает к схеме БД.  
Storage API — key-value, без схемы.

Плагины НЕ должны знать структуру БД.

**Статус:** Stable (неизменяемое решение)

### Почему async?

- Плагины могут быть I/O-bound
- EventBus требует асинхронности
- Удобно для фоновых задач

**Статус:** Stable (неизменяемое решение)

### Почему одна таблица для Storage?

Простота, гибкость, независимость от домена.

Если нужны сложные запросы — создай плагин с индексами поверх Storage API.

**Статус:** Stable (неизменяемое решение)

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

**Статус:** Stable (рекомендуемый паттерн)

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

**Статус:** Stable (рекомендуемый паттерн)

### Паттерн: State Machine

```python
# Используем StateEngine для отслеживания состояний
await state_engine.set("system.mode", "normal")

# Плагины проверяют состояние перед действием
mode = await state_engine.get("system.mode")
if mode == "maintenance":
    return  # Не выполнять действие
```

**Статус:** Stable (рекомендуемый паттерн)

---

## Remote Plugins

**Статус:** Experimental (реализовано частично)

### Цель
Поддержка плагинов, работающих в отдельных процессах/на других машинах.

### Архитектура
```
┌───────────────┐         ┌──────────────┐
│ Core Runtime  │ ←────→  │ Remote Plugin│
│               │  HTTP   │   (Process)  │
└───────────────┘         └──────────────┘
```

### Контракты
- EventBus → HTTP (future: gRPC stream)
- ServiceRegistry → HTTP unary call
- Storage API → HTTP unary call

### Требования
- Никаких shared memory
- Никаких прямых DB-коннектов
- Сериализация всех данных

**Подробнее:** [05-REMOTE-PLUGIN-CONTRACT.md](05-REMOTE-PLUGIN-CONTRACT.md)

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

**Статус:** Stable (документированный способ расширения)

### Добавить мониторинг

Создай плагин `monitoring`:
- Подписывается на все события
- Собирает метрики
- Отправляет в систему мониторинга

**Статус:** Stable (рекомендуемый паттерн)

### Добавить HTTP API

Создай плагин `api_gateway`:
- Поднимает FastAPI
- Вызывает сервисы через ServiceRegistry
- Публикует события через EventBus

**Статус:** Stable (рекомендуемый паттерн)

---

## Аутентификация и интеграции (рекомендация)

**Статус:** Stable (рекомендуемый паттерн)

Для ясности архитектуры и упрощения замены интеграций рекомендуется разделять ответственность за аутентификацию и за работу с устройствами.

- Плагин `oauth_yandex` отвечает ТОЛЬКО за OAuth flow: получение/обмен кодов, хранение `access_token`/`refresh_token` через `runtime.storage` и предоставление сервисов (`oauth_yandex.get_tokens`, `oauth_yandex.set_tokens`, и т.д.).
- Плагин интеграции `yandex_smart_home` (или его замена) использует сервисы `oauth_yandex` для доступа к токенам через `ServiceRegistry` и не должен импортировать или напрямую вызывать код `oauth_yandex`.

Это разделение позволяет:
- безопасно тестировать заглушки (stub) без реального OAuth;
- заменять stub реальной интеграцией без изменения аутентификационной логики;
- снижать область влияния при изменениях в механизме аутентификации.

---

## Ограничения

### Текущие (могут быть устранены в будущем)

**Статус:** Transitional

- Нет транзакций в Storage API
- Нет распределённых событий
- Нет персистентности EventBus
- Нет rate limiting

### Намеренные (не будут реализованы в Core)

**Статус:** Stable (неизменяемые ограничения)

- Нет ORM (используй Storage API)
- Нет HTTP в ядре (создай плагин)
- Нет бизнес-логики в Core
- Нет прямого доступа к БД

---

## Безопасность

### Изоляция плагинов

**Статус:** Stable (текущее ограничение)

Плагины работают в одном процессе → нет полной изоляции.

Для критичных плагинов используй Remote Plugins.

### Валидация данных

**Статус:** Stable (текущее ограничение)

Core Runtime НЕ валидирует данные плагинов.

Плагины сами отвечают за валидацию.

### Аутентификация

**Статус:** Stable (текущее ограничение)

Нет встроенной аутентификации.

Создай плагин `auth` для этого.

---

## Производительность

### EventBus
- O(n) где n = количество подписчиков
- Параллельная обработка всех подписчиков
- Не блокирует publisher

**Статус:** Stable (текущие характеристики)

### ServiceRegistry
- O(1) поиск сервиса
- Синхронный вызов
- Может быть bottleneck

**Статус:** Stable (текущие характеристики)

### Storage API
- Зависит от адаптера
- SQLite: O(log n) для индексированных полей
- Нет кэширования (добавь через плагин)

**Статус:** Stable (текущие характеристики)

### StateEngine
- O(1) операции (dict lookup)
- In-memory, очень быстро
- Требует lock для thread-safety

**Статус:** Stable (текущие характеристики)

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

**Статус:** Stable (рекомендуемый подход)

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

**Статус:** Stable (рекомендуемый подход)

---

## Заключение

Core Runtime — это **kernel**, а не **application**.

Он должен быть:
- Минимальным
- Стабильным
- Предсказуемым

Вся бизнес-логика — в плагинах и модулях.

---

**См. также:**
- [02-MODULES-AND-PLUGINS.md](02-MODULES-AND-PLUGINS.md) — различия между modules и plugins
- [04-CORE-RUNTIME-CONTRACT.md](04-CORE-RUNTIME-CONTRACT.md) — детальные гарантии и ограничения
- [03-QUICKSTART.md](03-QUICKSTART.md) — примеры использования

