# Application Use-Case Model

> **Статус документа:** Descriptive (complement to 01-ARCHITECTURE.md)  
> **Версия:** 0.1.0  
> **Последнее изменение:** 2026-01-31  
> **Аудитория:** Разработчики, архитекторы

---

## Что это и зачем?

Этот документ **НЕ вводит новую архитектуру**.

Он фиксирует **фактическую модель исполнения use-case'ов** в текущей системе.

**Проблема, которую решает:**
- "Где на самом деле реализуется поведение?"
- "Почему AdminModule такой большой?"
- "Что такое сервис, операция, handler?"
- "Где объявляются use-case'ы?"

После этого документа вы не будете искать "одну функцию, которая реализует use-case".

---

## Часть A: Три типа callable сущностей

В системе существует три принципиально разных типа вызываемых объектов. Они играют разные роли, регистрируются по-разному, и вызываются в разных контекстах.

### 1. Application Service (сервис приложения)

**Что это:**
- Асинхронная функция, которая реализует **внешний интерфейс use-case'а**
- Связывает HTTP request с внутренним состоянием системы
- Точка входа из внешнего мира (HTTP, CLI)

**Где живёт:**
- Обычно в `modules/{name}/` или в модуле, который работает с HTTP-слоем
- **Сейчас:** большинство application services в `modules/admin/module.py` (inline async функции)

**Примеры имён:**
```
admin.v1.runtime         — получить info о runtime
admin.devices.get        — получить информацию об устройстве
admin.operations.create  — создать операцию
admin.auth.login         — логин пользователя
```

**Характеристики:**
- Парсит HTTP параметры (path params, query string, JSON body)
- Проверяет авторизацию (проходит через ACL middleware)
- Может быть простой (прямой вызов domain service)
- Или составной (использует Operation subsystem)
- Возвращает результат в формате, удобном для HTTP (dict, list, etc)

**Регистрация:**
```python
await service_registry.register("admin.devices.get", admin_devices_get)
# или с ACL
await service_registry.register_with_acl("admin.devices.get", admin_devices_get, admin_only=True)
```

**Вызов:**
```python
result = await service_registry.call("admin.devices.get", device_id="lamp_kitchen")
```

**Чем НЕ является:**
- ❌ Не domain service (не содержит бизнес-логику домена)
- ❌ Не handler операции (не работает с OperationManager)
- ❌ Не обработчик события (не подписана на EventBus)

---

### 2. Operation (операция)

**Что это:**
- Именованное действие в системе, которое должно быть **отслежено и аудитировано**
- Содержит метаданные: инициатор, параметры, статус, результат, ошибку
- Может быть долгоживущим, переполняемым, отменяемым

**Когда используется:**
- **Критичные действия:** set device state, sync with external API, manage users
- **Долгоживущие операции:** sync devices from Yandex (минут)
- **Действия, которые нужно переполнять:** retry failed operation

**Чем отличается от Application Service:**
- Service — это синхронный вызов функции
- Operation — это создание объекта со статусом, который управляется OperationManager
- Service может завершиться за 10ms, Operation может переполняться часами
- Service регистрируется в ServiceRegistry, Operation регистрируется в OperationManager

**Жизненный цикл:**
```
1. create()   → Operation(PENDING)
2. execute()  → Operation(RUNNING) → Operation(SUCCESS/FAILED)
3. cancel()   → Operation(CANCELLED)
4. retry()    → новая Operation (PENDING)
```

**Сейчас существуют операции:**
```
device.set_state              — установить состояние устройства
yandex.sync                   — синхронизация с Яндексом
yandex.check_devices_online   — проверить online-статус
oauth.refresh_token           — обновить OAuth токен
mappings.create               — создать маппинг устройств
mappings.delete               — удалить маппинг
mappings.auto                 — автоматический маппинг
```

**Где живёт:**
- `core/operations.py` — OperationManager, Operation класс, OperationStatus enum
- `modules/operations/handlers.py` — обработчики операций
- `modules/admin/module.py` — регистрация handlers (L55-63)

**Чем НЕ является:**
- ❌ Не function (это объект с состоянием, не просто callable)
- ❌ Не service (не регистрируется в ServiceRegistry по строковому имени)
- ❌ Не event (не отправляется в EventBus)

---

### 3. Domain Service (доменный сервис)

**Что это:**
- Асинхронная функция, которая реализует **чистую бизнес-логику домена**
- Работает с концепциями из domain model: Device, User, Automation, State
- НЕ знает про HTTP, авторизацию, операции

**Где живёт:**
- `modules/{domain}/` — например, `modules/devices/services.py`
- Регистрируется в ServiceRegistry по имени `{domain}.{action}`

**Примеры имён:**
```
devices.get                — получить устройство по ID
devices.list               — получить список устройств  
devices.set_state          — установить состояние устройства
automation.trigger         — запустить автоматизацию
presence.update            — обновить статус присутствия
yandex.sync_devices        — синхронизировать устройства
```

**Характеристики:**
- Работает с domain entities (Device, User, etc)
- Возвращает domain model, а не HTTP-friendly JSON
- Может быть вызвана из Application Service, из Handler, из другого Domain Service
- НЕ знает про HTTP, авторизацию, операции

**Регистрация:**
```python
await service_registry.register("devices.set_state", domain_devices_set_state)
```

**Вызов:**
```python
# Из Application Service
result = await service_registry.call("devices.set_state", device_id, new_state)

# Из Operation Handler
result = await context["runtime"].service_registry.call("devices.set_state", ...)
```

**Чем отличается от Application Service:**
- Application Service работает с HTTP (body, params)
- Domain Service работает с domain model (Device, State)
- Application Service проверяет авторизацию
- Domain Service не должен знать про авторизацию
- Application Service может использовать несколько domain services

**Чем НЕ является:**
- ❌ Не operation handler (handler использует domain service)
- ❌ Не application service (это более низкоуровневый слой)
- ❌ Не event handler (хотя может быть вызван из event handler)

---

## Часть B: Каноническая цепочка выполнения use-case

Типичный use-case проходит через несколько слоёв. Вот каноническая цепочка:

```
┌─────────────────────────────────────────────────────────────────┐
│ HTTP Request                                                    │
│ POST /admin/v1/operations                                       │
│ Body: {type: "device.set_state", params: {...}}                │
└─────────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│ ApiModule (HTTP adapter)                                        │
│ - Парсит HTTP: body, path params, query params                 │
│ - Проверяет auth на boundary-layer                             │
│ - Находит service name из HttpRegistry                          │
│ - Вызывает service через ServiceRegistry                        │
└─────────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│ Application Service (service layer)                             │
│ Example: admin_operations_create(body: {type, params})          │
│ Роль: парсить данные, вызвать нижестоящие слои                 │
└─────────────────────────────────────────────────────────────────┘
                          ↓
       ┌──────────────────────────────────────────┐
       │ Выбор пути: с Operation или без?          │
       └──────────────────────────────────────────┘
              /                          \
             /                            \
            ↓                              ↓
    ┌─────────────────┐         ┌──────────────────────┐
    │ ПУТЬ 1          │         │ ПУТЬ 2               │
    │ С Operation     │         │ Без Operation        │
    │                 │         │ (простые запросы)    │
    └─────────────────┘         └──────────────────────┘
            ↓                              ↓
┌─────────────────────────────────┐  ┌──────────────────┐
│ OperationManager.create()       │  │ Domain Service   │
│ OperationManager.execute()      │  │ (direct call)    │
│ Создаёт Operation(PENDING)      │  │                  │
│ Запускает handler               │  └──────────────────┘
└─────────────────────────────────┘         ↓
            ↓                          Result
┌─────────────────────────────────┐
│ Operation Handler               │
│ Example: handle_device_set_state│
│ Роль: бизнес-логика операции   │
└─────────────────────────────────┘
            ↓
┌─────────────────────────────────┐
│ Domain Service (вложенный вызов)│
│ Например: devices.set_state     │
│ Роль: чистая бизнес-логика     │
└─────────────────────────────────┘
            ↓
        Result
            ↓
┌─────────────────────────────────┐
│ HTTP Response                   │
│ {status, result, error}         │
└─────────────────────────────────┘
```

### Обязательные шаги

1. **HTTP Request** — всегда (это entry point)
2. **HTTP Adapter** — всегда (парсит параметры)
3. **Application Service** — всегда (точка входа в ядро)

### Опциональные шаги

- **Operation Manager** — если это долгоживущее/аудитируемое действие
- **Operation Handler** — только если используется Operation
- **Domain Service** — может быть вызван прямо из Application Service

### Случай с Operation

Если Application Service использует Operation:

```
Application Service
    ↓
Operation.create()        ← создаёт с PENDING
Operation.execute()       ← меняет на RUNNING
    ↓
Operation Handler
    ↓
Domain Service(s)         ← вложенные вызовы
    ↓
Operation.finished_at     ← меняет на SUCCESS/FAILED
    ↓
Return Operation result
```

### Случай без Operation

Если Application Service вызывает Domain Service напрямую:

```
Application Service
    ↓
Domain Service (direct call)
    ↓
Return result
```

---

## Часть C: Роль ServiceRegistry и HttpRegistry

### ServiceRegistry

**Что хранит:**
```python
Dict[str_name → async_function]
```

Примеры:
```
"admin.v1.runtime"      → async def admin_v1_runtime()
"devices.get"           → async def domain_devices_get(device_id)
"admin.operations.list" → async def admin_operations_list(limit, offset)
```

**Как регистрируется:**
```python
await service_registry.register("name", func)
# или
await service_registry.register_with_acl("name", func, admin_only=True)
```

**Как вызывается:**
```python
result = await service_registry.call("name", *args, **kwargs)
```

**ВАЖНОЕ: Что НЕ гарантирует ServiceRegistry**

❌ Что функция имеет определённую сигнатуру
```python
# Одна функция может быть
async def admin_v1_runtime() -> Dict:

# Другая может быть
async def admin_devices_get(id, body=None, **kwargs):

# Третья может быть
async def admin_operations_list(limit=100, offset=0, status=None, **kwargs):
```

❌ Что функция НЕ обёрнута middleware'ом
```python
# Когда регистрируешь через register_with_acl(),
# ServiceRegistry автоматически оборачивает функцию в wrapper:
async def wrapped(*args, **kwargs):
    ctx = acl.current_context()
    if admin_only:
        acl.enforce_admin(ctx)
    result = await original_func(*args, **kwargs)
    if filter_result:
        result = acl.filter_with_policy(ctx, resource, result)
    return result

# В реестре хранится wrapped, а не original_func
```

❌ Что функция — это одна функция
```python
# Часто одна Application Service просто делегирует другой:
async def admin_v1_runtime():
    return await service_registry.call("system.get_runtime_info")
```

**Роль ServiceRegistry:**

✅ Обеспечивает динамическую маршрутизацию по имени (RPC-like)  
✅ Позволяет плагинам взаимодействовать без импортирования кода друг друга  
✅ Обеспечивает ACL middleware для авторизации  

---

### HttpRegistry

**Что хранит:**
```python
List[HttpEndpoint]

where HttpEndpoint = {
    method: str           # GET, POST, PUT, DELETE
    path: str             # /admin/v1/operations
    service: str          # admin.operations.list
    description: str
}
```

**Как регистрируется:**
```python
# В modules/admin/module.py:
http_endpoints = [
    HttpEndpoint(method="POST", path="/admin/v1/operations", 
                 service="admin.operations.create"),
    HttpEndpoint(method="GET", path="/admin/v1/operations", 
                 service="admin.operations.list"),
]
for ep in http_endpoints:
    runtime.http.register(ep)
```

**Зачем существует:**
- Декларативный реестр HTTP контрактов
- Источник правды для API documentation
- Проекция на HTTP adapter (ApiModule)

**Почему декларативный:**
- HTTP contract — это метаданные, не исполняемый код
- Адаптер читает контракты и создаёт маршруты
- Позволяет адаптерам быть простыми и заменяемыми
- Версионирование и deprecation простые

**Почему НЕ источник бизнес-логики:**
- HttpRegistry содержит ТОЛЬКО метаданные (path, method, service name)
- Реальная функция живёт в ServiceRegistry
- HttpRegistry — это только маппинг

**Как ApiModule использует HttpRegistry:**
```
1. Получает список endpoints: runtime.http.list()
2. Для каждого endpoint создаёт FastAPI handler
3. Handler парсит HTTP параметры
4. Handler вызывает сервис: service_registry.call(endpoint.service, **params)
5. Возвращает result
```

---

## Часть D: Что считается use-case в проекте

### Неправильное понимание ❌

❌ "Use-case = одна функция"

Use-case может состоять из нескольких слоёв функций:
- Application Service (точка входа)
- Operation Handler (бизнес-логика операции)
- Domain Service (чистая логика домена)

❌ "HTTP endpoint = use-case"

HTTP endpoint это **только вход**. Use-case может быть более сложным.

Например, `POST /admin/v1/operations` с `type: "device.set_state"`:
- Application Service: `admin.operations.create()`
- Operation Handler: `handle_device_set_state()`
- Domain Service: `devices.set_state()`

Это один use-case, но три слоя.

### Правильное понимание ✅

**Use-case = цепочка вызовов от HTTP request до результата**

Примеры:

**Use-case 1: Get device info (простой)**
```
HTTP GET /admin/v1/devices/{id}
    ↓
admin_devices_get(id)                         [App Service]
    ↓
domain_devices_get(id)                        [Domain Service]
    ↓
Device object
    ↓
HTTP Response {id, name, state, ...}
```

**Use-case 2: Set device state (с операцией)**
```
HTTP POST /admin/v1/operations
Body: {type: "device.set_state", params: {...}}
    ↓
admin_operations_create(body)                 [App Service]
    ↓
OperationManager.create()
OperationManager.execute()
    ↓
handle_device_set_state(params)               [Handler]
    ↓
domain_devices_set_state(device_id, state)    [Domain Service]
    ↓
Operation {id, status: "success", result}
    ↓
HTTP Response {operation_id, status, result}
```

**Use-case 3: Login user (с токенами)**
```
HTTP POST /admin/v1/auth/login
Body: {user_id, password}
    ↓
admin_auth_login(user_id, password)           [App Service]
    ↓
verify_user_password()
generate_access_token()
create_refresh_token()
    ↓
HTTP Response {access_token, refresh_token, ...}
```

### Где объявляется use-case?

**Ответ: не в одном месте.**

Use-case "объявляется" в виде цепочки:

1. **HTTP entry point** — HttpRegistry + ApiModule (как туда попасть)
2. **Application Service** — AdminModule (что сделать с HTTP params)
3. **Operation или Domain Service** — modules/* (как выполнить бизнес-логику)
4. **HTTP response** — ApiModule (как вернуть результат)

Нет одного файла, где можно сказать "вот здесь определён use-case X".

---

## Часть E: Почему AdminModule такой большой

### Цифры

`modules/admin/module.py`:
- 1309 строк
- ~45 Application Services
- ~50 HTTP endpoints

### Почему?

AdminModule содержит все **административные Application Services**.

Это не архитектурный дефект — это логичная группировка.

Все Application Services, которые доступны через HTTP `/admin/*`, это:
- операции (create, list, get, cancel, retry)
- инвентаризация (runtime, plugins, services, http, events, storage, state)
- управление устройствами (list, get, set_state, mappings, external)
- управление интеграциями (list)
- управление авторизацией (users, api-keys, sessions, login, refresh, etc)
- управление Яндексом (sync, check-online)

Это 45+ разных use-case'ов, все они административные.

### Почему они не разделены на разные файлы?

**Текущая модель:**
```
modules/admin/module.py
├─ admin_v1_runtime()
├─ admin_v1_plugins()
├─ admin_devices_list()
├─ admin_auth_login()
├─ admin_operations_create()
└─ ... 40+ функций
```

**Почему это плохо:**
- 1309 строк в одном файле
- Сложно ориентироваться
- Сложно find'ить функцию

**Почему это пока оставлено так:**
- Application Services это не бизнес-логика
- Они просто парсят HTTP параметры и вызывают domain services или operations
- Разделение на подмодули (`admin/routes/operations.py`, `admin/routes/auth.py`) было бы косметическим улучшением
- Архитектурный рефакторинг (перенос в `adapters/http/`) требует больше работы

### Выход?

**Вариант 1: Разделить AdminModule на подмодули**
```
modules/admin/
├─ module.py              # register() + общая логика
├─ services/
│  ├─ runtime.py
│  ├─ devices.py
│  ├─ auth.py
│  ├─ operations.py
│  └─ ...
```

**Вариант 2: Переместить в adapters/inbound/http/**
```
adapters/inbound/http/
├─ admin_routes.py        # все /admin/* endpoints
├─ operations_routes.py    # все /admin/operations endpoints
├─ auth_routes.py          # все /admin/auth endpoints
```

**Сейчас:** остаётся как есть (большой модуль, но функциональный).

---

## Часть F: Частые ошибки в понимании

### Ошибка 1: "Service = Domain Service"

**Неправильно:**
> У нас есть сервис `admin.devices.get`, значит это Domain Service

**Правильно:**
- `admin.devices.get` — это Application Service
- Он вызывает Domain Service `devices.get` внутри
- Application Service может быть просто прокси для domain service
- Или может быть сложнее (проверка auth, парсинг HTTP, преобразование результата)

---

### Ошибка 2: "Operation = Service"

**Неправильно:**
> У нас есть operation `device.set_state`, это сервис

**Правильно:**
- Operation это именованное действие с состоянием
- Operation регистрируется в OperationManager, не в ServiceRegistry
- Operation не просто callable — это объект с full lifecycle
- Operation может быть отменён, переполнен, сохранён в БД

---

### Ошибка 3: "Handler = Operation"

**Неправильно:**
> У нас есть handler `handle_device_set_state`, это операция

**Правильно:**
- Handler это функция, которая выполняет логику операции
- Handler вызывается из OperationManager.execute()
- Handler может вызывать domain services
- Operation это объект, Handler это функция

---

### Ошибка 4: "HTTP endpoint = use-case"

**Неправильно:**
> `POST /admin/v1/operations` это один use-case

**Правильно:**
- `/admin/v1/operations` это только точка входа
- Use-case определяется параметром `type` (device.set_state, yandex.sync, etc)
- Один HTTP endpoint может реализовать несколько use-case'ов

---

### Ошибка 5: "HttpRegistry = API specification"

**Неправильно:**
> HttpRegistry содержит полную спецификацию API

**Правильно:**
- HttpRegistry содержит только метаданные: {method, path, service_name}
- Параметры функции определяются функцией (service name -> ServiceRegistry -> функция)
- Типы параметров не описаны в HttpRegistry
- HttpRegistry это **только маппинг, не спецификация**

---

### Ошибка 6: "Я хочу создать new use-case"

**Неправильно (и где это делать):**
> Я создам новый файл `modules/my_feature/use_case.py` с use-case'ом

**Правильно (что нужно сделать):**

Use-case это не один файл, а цепочка:

1. **Регистрирую HTTP endpoint** в HttpRegistry
   ```python
   HttpEndpoint(method="POST", path="/my/feature", service="my.feature.create")
   ```

2. **Создаю Application Service** (обычно в модуле)
   ```python
   async def my_feature_create(body):
       ...
   ```

3. **Регистрирую в ServiceRegistry**
   ```python
   await service_registry.register("my.feature.create", my_feature_create)
   ```

4. **Если нужна операция, регистрирую handler**
   ```python
   async def handle_my_feature_create(params):
       ...
   ops_mgr.register_handler("my.feature.create", handle_my_feature_create)
   ```

5. **Реализую domain logic** (вспомогательные функции)
   ```python
   async def domain_my_feature_process(data):
       ...
   ```

---

## Итого: Mental Model

### Система работает на трёх уровнях

| Уровень | Тип | Где | Регистрация | Вызов | Назначение |
|---------|-----|-----|-------------|-------|-----------|
| **HTTP** | Entry point | HttpRegistry | `runtime.http.register()` | ApiModule | Точка входа |
| **Application** | Function | modules/* | ServiceRegistry | `service_registry.call()` | Парсит HTTP, вызывает lower levels |
| **Operation** | Manager | core/operations.py | OperationManager | `operations.create()/.execute()` | Долгоживущие, аудитируемые действия |
| **Handler** | Function | modules/operations/ | OperationManager | `operations.execute()` | Бизнес-логика операции |
| **Domain** | Function | modules/{domain}/ | ServiceRegistry | `service_registry.call()` | Чистая бизнес-логика |

### Цепочка выполнения (canonical)

```
HTTP Request
    ↓
HttpRegistry lookup (method + path)
    ↓
ApiModule handler (HTTP adapter)
    ↓
ServiceRegistry lookup (service name)
    ↓
Application Service (exec with HTTP params)
    ↓ (optional)
OperationManager.create() + execute()
    ↓ (if operation)
Operation Handler (exec with operation params)
    ↓ (optional)
Domain Service (exec with domain params)
    ↓
Result to HTTP Response
```

### Где реализуется use-case?

**Ответ: в цепочке слоёв, не в одном месте**

- **What to call** → HttpRegistry + Application Service
- **How to execute** → Operation Handler (optional)
- **What to do** → Domain Service

Это разделение ответственности, не дефект дизайна.

---

## Справка для разработчиков

### Я пишу новый use-case. Что мне нужно?

1. **HTTP endpoint** → добавить в HttpRegistry
2. **Application Service** → async function in module
3. **Operation** (optional) → если долгоживущее/аудитируемое
4. **Handler** (optional) → если используется Operation
5. **Domain Service** (optional) → если нужна чистая логика

### Я хочу понять, как работает use-case "device.set_state"

Следи цепочку:
1. HTTP: `POST /admin/v1/operations` → HttpRegistry
2. Service: `admin.operations.create` → modules/admin/module.py:1040
3. Operation: создаётся `Operation(type="device.set_state")`
4. Handler: `handle_device_set_state` → modules/operations/handlers.py:13
5. Domain: `devices.set_state` → modules/devices/services.py

### Я вижу большой модуль. Что это значит?

Большой модуль (AdminModule, 1309 строк) значит:
- ✅ Много Application Services в одном месте
- ✅ Логичная группировка (все `/admin/*` endpoints)
- ❌ Могло бы быть разделено на подмодули (рефакторинг)
- ❌ Не означает архитектурный дефект

---

## Дополнительные материалы

**Связанные документы:**
- [01-ARCHITECTURE.md](01-ARCHITECTURE.md) — архитектурные инварианты
- [04-CORE-RUNTIME-CONTRACT.md](04-CORE-RUNTIME-CONTRACT.md) — контракт Core
- [07-RUNTIME-MODULE-CONTRACT.md](07-RUNTIME-MODULE-CONTRACT.md) — контракт Module
- [FORENSIC_ANALYSIS_SERVICES.md](../FORENSIC_ANALYSIS_SERVICES.md) — детальный анализ

**Код:**
- Application Services: [modules/admin/module.py](../modules/admin/module.py#L96-L1250)
- Operation Manager: [core/operations.py](../core/operations.py)
- Operation Handlers: [modules/operations/handlers.py](../modules/operations/handlers.py)
- HTTP Adapter: [modules/api/module.py](../modules/api/module.py#L139-L330)
