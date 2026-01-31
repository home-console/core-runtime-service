# Forensic Analysis: Как система РЕАЛЬНО работает сейчас

*Дата анализа: 2026-01-31*  
*Проект: core-runtime-service (plugin-based runtime)*

---

## A. Краткая карта системы

### Где что живёт:

```
┌─────────────────────────────────────────────────────────────────┐
│ HTTP Request                                                    │
└─────────────────────────────────────────────────────────────────┘
              ↓ (ApiModule.handler)
┌─────────────────────────────────────────────────────────────────┐
│ HttpRegistry (declarative mapping)                              │
│ - path: "/admin/v1/operations"                                  │
│ - method: "POST"                                                │
│ - service: "admin.operations.create"  ← THIS IS KEY             │
└─────────────────────────────────────────────────────────────────┘
              ↓ (lookup in ServiceRegistry)
┌─────────────────────────────────────────────────────────────────┐
│ ServiceRegistry._services dict                                  │
│ "admin.operations.create" → async def admin_operations_create() │
└─────────────────────────────────────────────────────────────────┘
              ↓ (await func(*args, **kwargs))
┌─────────────────────────────────────────────────────────────────┐
│ OperationManager (operations subsystem)                         │
│ - Calls: runtime.operations.create()                            │
│ - Looks up: _handlers["device.set_state"]                       │
│ - Executes: handle_device_set_state() from handlers.py          │
└─────────────────────────────────────────────────────────────────┘
              ↓ (back to service layer)
┌─────────────────────────────────────────────────────────────────┐
│ ServiceRegistry.call("devices.set_state", ...)  (nested call)   │
│ Returns operation result to client                              │
└─────────────────────────────────────────────────────────────────┘
```

### Три уровня "сервис-подобных" объектов:

| Уровень | Где объявляется | Регистрация | Вызов |
|---------|-----------------|------------|-------|
| **Services** | `modules/admin/module.py` (inline async functions) | `service_registry.register()` | `service_registry.call("name", ...)` |
| **Operations** | `core/operations.py` (Operation class) | `operations.register_handler()` | `operations.create() → operations.execute()` |
| **Handlers** | `modules/operations/handlers.py` (async functions) | `operations.register_handler("type", func)` | вызываются из `OperationManager.execute()` |

---

## B. Таблица: Service → Function → File

### Основные Admin Services

| Service Name | Function | Файл | Тип | Регистрация |
|--------------|----------|------|-----|-------------|
| `admin.v1.runtime` | `admin_v1_runtime()` | [modules/admin/module.py](modules/admin/module.py#L96) | AsyncFunc | `register_with_acl()` L1229 |
| `admin.v1.plugins` | `admin_v1_plugins()` | [modules/admin/module.py](modules/admin/module.py#L109) | AsyncFunc | `register_with_acl()` L1229 |
| `admin.v1.services` | `admin_v1_services()` | [modules/admin/module.py](modules/admin/module.py#L169) | AsyncFunc | `register_with_acl()` L1229 |
| `admin.v1.http` | `admin_v1_http()` | [modules/admin/module.py](modules/admin/module.py#L177) | AsyncFunc | `register_with_acl()` L1229 |
| `admin.devices.list` | `admin_devices_list()` | [modules/admin/module.py](modules/admin/module.py#L268) | AsyncFunc | `register_with_acl()` L1229 |
| `admin.devices.get` | `admin_devices_get()` | [modules/admin/module.py](modules/admin/module.py#L271) | AsyncFunc | `register_with_acl()` L1229 |
| `admin.devices.set_state` | `admin_devices_set_state()` | [modules/admin/module.py](modules/admin/module.py#L278) | AsyncFunc | `register_with_acl()` L1229 |
| `admin.auth.me` | `admin_auth_me()` | [modules/admin/module.py](modules/admin/module.py) | AsyncFunc | `register_with_acl()` L1229 |
| `admin.auth.login` | `admin_auth_login()` | [modules/admin/module.py](modules/admin/module.py) | AsyncFunc | `register()` L1231 |
| `admin.auth.initialize` | `admin_auth_initialize()` | [modules/admin/module.py](modules/admin/module.py) | AsyncFunc | `register()` L1231 |
| `admin.operations.create` | `admin_operations_create()` | [modules/admin/module.py](modules/admin/module.py) | AsyncFunc | `register_with_acl()` L1229 |
| `admin.operations.list` | `admin_operations_list()` | [modules/admin/module.py](modules/admin/module.py) | AsyncFunc | `register_with_acl()` L1229 |

**Всего сервисов:** 45+ (см. `service_registrations` список на L1172)

### Operation Handlers

| Operation Type | Handler | Файл | Регистрация |
|---|---|---|---|
| `device.set_state` | `handle_device_set_state()` | [modules/operations/handlers.py](modules/operations/handlers.py) | `ops_mgr.register_handler()` L57 [modules/admin/module.py](modules/admin/module.py#L57) |
| `yandex.sync` | `handle_yandex_sync()` | [modules/operations/handlers.py](modules/operations/handlers.py) | `ops_mgr.register_handler()` L58 |
| `yandex.check_devices_online` | `handle_yandex_check_online()` | [modules/operations/handlers.py](modules/operations/handlers.py) | `ops_mgr.register_handler()` L59 |
| `oauth.refresh_token` | `handle_oauth_refresh()` | [modules/operations/handlers.py](modules/operations/handlers.py) | `ops_mgr.register_handler()` L60 |
| `mappings.create` | `handle_mappings_create()` | [modules/operations/handlers.py](modules/operations/handlers.py) | `ops_mgr.register_handler()` L61 |
| `mappings.delete` | `handle_mappings_delete()` | [modules/operations/handlers.py](modules/operations/handlers.py) | `ops_mgr.register_handler()` L62 |
| `mappings.auto` | `handle_mappings_auto()` | [modules/operations/handlers.py](modules/operations/handlers.py) | `ops_mgr.register_handler()` L63 |

---

## C. Ответ на ключевой вопрос

### "Можно ли сейчас однозначно сказать, что service = function?"

**Ответ: ЧАСТИЧНО (с оговорками)**

### Истина и лжь:

✅ **ПРАВДА:**
- Service в ServiceRegistry это 100% async function: `ServiceFunc = Callable[..., Awaitable[Any]]`
- Регистрация: `await service_registry.register(name, func)`
- Вызов: `result = await service_registry.call(name, *args, **kwargs)`
- **Функция напрямую вызывается через registry**

❌ **НО (важные оговорки):**

1. **Функции оборачиваются middleware'ом ACL**
   - Оригинальная функция регистрируется в `register_with_acl()`
   - Создаётся wrapper функция, которая:
     - проверяет авторизацию (admin_only)
     - проверяет policies
     - фильтрует результат
   - **В реестр попадает wrapper, не оригинальная функция**
   - [core/service_registry.py L145-230](core/service_registry.py#L145-L230)

2. **Функции в AdminModule имеют разные контракты**
   ```python
   # Одни: полностью generic
   async def admin_v1_runtime() -> Dict[str, Any]:
   
   # Другие: требуют path params
   async def admin_devices_get(id: Optional[str] = None, **kwargs):
   
   # Третьи: требуют body
   async def admin_devices_set_state(id: Optional[str] = None, body: Any = None, **kwargs):
   ```
   - Нет единого контракта
   - HTTP adapter сам парсит params, body, path

3. **Некоторые сервисы вызывают другие сервисы внутри**
   ```python
   async def admin_operations_create(body: Any = None, **kwargs):
       # Это сервис, который вызывает:
       operation = await ops_mgr.create(op_type, params, initiator)
       result = await ops_mgr.execute(operation)
       # OperationManager.execute() вызывает handler
       # Handler вызывает service_registry.call("devices.set_state", ...)
   ```
   - **Разные типы вызовов (service → operation → handler → service)**

4. **Operations это НЕ сервисы**
   - Operation это data structure + manager
   - `OperationManager.execute()` вызывает handler, не service
   - Handler вызывает services через `runtime.service_registry.call()`
   - **Смешанная архитектура**

### Вывод на вопрос:

**НЕТ, service ≠ function в чистом смысле**

Правильнее сказать: **service = функция + middleware обёртка + контракт**

---

## D. Список мест, которые вызывают путаницу

### 1. **Три разных способа регистрации функций**

```python
# Способ 1: базовый register
await service_registry.register("admin.v1.runtime", admin_v1_runtime)

# Способ 2: с ACL
await service_registry.register_with_acl("admin.v1.plugins", admin_v1_plugins, admin_only=True)

# Способ 3: с middleware
await service_registry.register_with_middleware("x", func, [LogMiddleware()])
```

**Путаница:** непонятно, когда использовать какой способ

**В коде:** [modules/admin/module.py L1229-1231](modules/admin/module.py#L1229-L1231)

---

### 2. **Двойная регистрация + оборачивание**

```python
# В AdminModule регистрируются функции:
async def admin_devices_set_state(id, body, **kwargs):
    # ... логика ...
    return {operation_id, status, result, error}

# register_with_acl создаёт wrapper:
async def wrapped(*args, **kwargs):
    ctx = acl.current_context()
    if effective_admin_only:
        acl.enforce_admin(ctx)
    result = await func(*args, **kwargs)  # вызов оригинальной
    if filter_result:
        result = acl.filter_with_policy(ctx, resource, result)
    return result

# В реестр попадает wrapped, НЕ оригинальная admin_devices_set_state
```

**Путаница:** какая функция вызывается на самом деле?

**В коде:** [core/service_registry.py L145-230](core/service_registry.py#L145-L230)

---

### 3. **Разные уровни вызовов не разделены явно**

```
HTTP Request
    ↓
ApiModule.handler → service_registry.call("admin.operations.create")
    ↓
AdminModule.admin_operations_create()
    ↓
OperationManager.execute() ← это НЕ service, это manager
    ↓
OperationManager._handlers["device.set_state"] ← это handler, НЕ service
    ↓
modules/operations/handlers.handle_device_set_state()
    ↓
service_registry.call("devices.set_state", ...) ← это уже service снова!
```

**Путаница:** service, operation, handler — всё похоже, но логика разная

---

### 4. **Контракт функций неопределённый**

```python
# Некоторые принимают только **kwargs:
async def admin_v1_runtime() -> Dict[str, Any]:

# Некоторые берут path param через имя:
async def admin_devices_get(id: Optional[str] = None, **kwargs):

# Некоторые берут body:
async def admin_devices_set_state(id: Optional[str] = None, body: Any = None, **kwargs):

# Некоторые берут query params:
async def admin_operations_list(limit: int = 100, offset: int = 0, status: Optional[str] = None, **kwargs):

# Некоторые берут request и response объекты:
async def admin_auth_me(request: Any = None) -> Dict[str, Any]:
```

**Путаница:** как узнать, какие параметры нужны?

**Ответ:** никак явно. ApiModule парсит сам.

**В коде:** [modules/api/module.py L170-360](modules/api/module.py#L170-L360)

---

### 5. **HTTP ↔ Service маппинг неявный**

HttpRegistry содержит декларативное описание:
```python
HttpEndpoint(
    method="POST",
    path="/admin/v1/operations",
    service="admin.operations.create",  ← строка, просто строка
    description="..."
)
```

ApiModule делает преобразование:
```python
# 1. Получает endpoint.service (строка)
# 2. Парсит HTTP request (path params, query params, body)
# 3. Подготавливает params dict
# 4. Вызывает:
result = await self.runtime.service_registry.call(endpoint.service, **params)
```

**Путаница:** 
- Как params попадают в функцию?
- Если функция ждёт `(id, body)`, а params это `{"id": "x", "body": {...}}`?
- Ответ: через `**params` распаковка

**В коде:** [modules/api/module.py L310-330](modules/api/module.py#L310-L330)

---

### 6. **Operations vs Services граница размыта**

Есть сервис `admin.operations.create`:
```python
async def admin_operations_create(body):
    op_type = body.get("type")
    params = body.get("params", {})
    operation = await ops_mgr.create(op_type, params, initiator)
    result = await ops_mgr.execute(operation)  ← execute вызывает handler
    return result.to_dict()
```

Внутри handler может вызвать сервис:
```python
async def handle_device_set_state(params, context):
    result = await runtime.service_registry.call("devices.set_state", ...)
    return result
```

**Путаница:** 
- Когда использовать operation?
- Когда вызвать service напрямую?
- Что такое handler — это отдельный тип сущности?

**В коде:** 
- Operations: [core/operations.py](core/operations.py)
- Handlers: [modules/operations/handlers.py](modules/operations/handlers.py)
- Service call: [modules/api/module.py L328](modules/api/module.py#L328)

---

### 7. **ACL оборачивание скрывает оригинальную функцию**

Что видит разработчик:
```python
async def admin_devices_list():
    return await runtime.service_registry.call("devices.list")

await service_registry.register_with_acl("admin.devices.list", admin_devices_list)
```

Что на самом деле в реестре:
```python
async def wrapped(*args, **kwargs):
    ctx = acl.current_context()
    acl.enforce_admin(ctx)  # ← если admin_only=True
    result = await admin_devices_list(*args, **kwargs)
    result = acl.filter_with_policy(ctx, "device", result)  # ← filter
    return result
```

**Путаница:** debugging, трассировка, error handling

---

## E. Вывод: Как система ФАКТИЧЕСКИ устроена

### Одним абзацем:

**Система имеет трёхуровневую архитектуру сервисов, которая не разделена явно:**

1. **HTTP → Service маршрут** — HttpRegistry содержит декларативные контракты (path → service name), ApiModule динамически создаёт FastAPI handlers, которые парсят HTTP-параметры и вызывают функции через ServiceRegistry по строковому имени.

2. **Service Registry** — содержит `Dict[str_name → async_function]`, но функции автоматически оборачиваются middleware (ACL, authorization, filtering) при регистрации через `register_with_acl()`, так что реальная функция в реестре — это wrapper, не оригинальная.

3. **Operations subsystem** — параллельный слой для длительных/критичных операций, содержит OperationManager (manager) и handlers (функции вида `async handle_*()`, регистрируются отдельно), handler'ы вызывают services через `service_registry.call()` внутри себя, создавая вложенность.

**Основная путаница:** service, operation, handler — разные типы вызываемых, но они переплетены в одной цепочке вызовов, и нет явного разделения. HTTP layer вызывает service, service может быть wrapper, service может быть operation manager, operation manager вызывает handler, handler вызывает service снова. Контракты функций неопределённые (разные параметры), маршрутизация HTTP → Service строковая, оборачивание скрывает оригинальные функции.

**Единой явной точки, где можно сказать "вот здесь объявляются use-case'ы", нет.** Use-case'ы размазаны:
- Операционные интерфейсы в AdminModule (`admin_*` функции)
- Бизнес-логика в operation handlers (`handle_*` функции)  
- Domain logic в modules services (`device.set_state`, `yandex.sync_devices`, etc.)

---

## Дополнительно: Точки регистрации в коде

### ServiceRegistry регистрация

| Файл | Строка | Метод | Что |
|------|--------|-------|-----|
| [modules/admin/module.py](modules/admin/module.py#L1229) | 1229 | `register_with_acl()` | Все admin.* сервисы |
| [modules/admin/module.py](modules/admin/module.py#L1231) | 1231 | `register()` | Публичные auth endpoints |

### OperationManager регистрация handlers

| Файл | Строка | Метод | Что |
|------|--------|-------|-----|
| [modules/admin/module.py](modules/admin/module.py#L55-L63) | 55-63 | `ops_mgr.register_handler()` | 7 operation handlers |

### HttpRegistry регистрация endpoints

| Файл | Строка | Метод | Что |
|------|--------|-------|-----|
| [modules/admin/module.py](modules/admin/module.py#L1239-L1287) | 1239-1287 | `runtime.http.register()` | 45+ HTTP endpoints |

### API маршрутизация

| Файл | Строка | Механизм | Что |
|------|--------|----------|-----|
| [modules/api/module.py](modules/api/module.py#L139-160) | 139-160 | `for ep in endpoints: @app.route()` | Dynamic route generation |
| [modules/api/module.py](modules/api/module.py#L328) | 328 | `service_registry.call()` | Service invocation |
