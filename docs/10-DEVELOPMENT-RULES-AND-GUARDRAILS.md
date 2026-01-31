# Development Rules and Guardrails

> **Статус документа:** Normative (binding for new code)  
> **Версия:** 1.0.0  
> **Дата:** 2026-01-31  
> **Область действия:** Весь новый и изменяемый код после этой даты

---

## Прежде всего

### Существующий код — это легаси по архитектуре

Всё, что написано до этого документа (включая текущий `modules/admin/module.py`):
- ✅ Работает
- ✅ Функционирует как задумано
- ❌ Не обязательно следует этим правилам

**Эти правила применяются СТРОГО к:**
- новому коду (новые функции, модули, endpoints)
- изменяемому коду (когда вы редактируете существующий файл)
- новым фичам и интеграциям

**Это НЕ требует:**
- переписывания AdminModule
- рефакторинга существующих сервисов
- разбиения модулей

Цель правил — **стабилизировать архитектуру на будущее**, не разбивая текущее.

---

## Часть 1: Три роли в системе

В системе ровно три типа callable объектов, каждая с чёткой ответственностью.

### Роль 1: Application Service

**Назначение:**
- точка входа из внешнего мира
- оркестрирует выполнение use-case

**Где живёт:**
- В модуле, который работает с HTTP-слоем
- Сейчас это `modules/admin/module.py`, `modules/api/module.py`
- Для новых фич: `modules/{name}/services.py` или прямо в `module.py`

**Имена:**
- `admin.*` — все административные сервисы
- `api.*` — все публичные API сервисы
- `{domain}.{action}` — доменные сервисы (опционально)

**Что МОЖНО:**
- ✅ Парсить и валидировать HTTP параметры (body, query, path)
- ✅ Выполнять ACL / authorization checks
- ✅ Вызывать Operation Manager (если долгоживущее)
- ✅ Вызывать Domain Services
- ✅ Трансформировать результат для HTTP ответа
- ✅ Публиковать события через EventBus
- ✅ Вызывать несколько domain services для одного use-case

**Что НЕЛЬЗЯ:**
- ❌ Содержать бизнес-логику более 1–2 уровней условных операторов
- ❌ Напрямую работать со storage (должно быть через domain service)
- ❌ Напрямую вызывать external adapters (yandex API, oauth clients)
- ❌ Реализовывать сложные conditional state machines
- ❌ Создавать новые domain entities
- ❌ Вызывать другие application services (косвенное управление)

**Признак нарушения:**
- Функция больше 30–40 строк (слишком сложна)
- Функция содержит 3+ уровня вложенности
- Функция знает про storage/db/adapter details
- Функция вызывает другой admin.* сервис

**Пример (правильно):**
```python
async def admin_devices_set_state(id: str, body: dict) -> dict:
    """Простая оркестрация: парс → call handler → return"""
    device_id = id or body.get("device_id")
    state = body.get("state", {})
    
    # Вызываем operation handler
    from core.operations import OperationInitiator, OperationInitiatorKind
    initiator = OperationInitiator(kind=OperationInitiatorKind.ADMIN)
    
    operation = await runtime.operations.create(
        "device.set_state",
        {"device_id": device_id, "state": state},
        initiator=initiator
    )
    result = await runtime.operations.execute(operation)
    
    return result.to_dict()
```

**Пример (неправильно):**
```python
async def admin_devices_set_state(id: str, body: dict) -> dict:
    """Слишком много логики здесь!"""
    device_id = id or body.get("device_id")
    
    # ❌ Прямой доступ к storage
    device = await runtime.storage.get("devices", device_id)
    
    # ❌ Сложная бизнес-логика
    if device["shared_with"] and not context.is_admin:
        # проверяю, может ли пользователь менять shared device
        if context.user_id not in device["shared_with"]:
            raise ForbiddenError()
    
    # ❌ Работаю с внешним API
    if device["provider"] == "yandex":
        await yandex_client.set_state(device["external_id"], body["state"])
    
    # ❌ Слишком большой условный оператор
    old_state = device.get("state", {})
    new_state = {**old_state, **body["state"]}
    ...
```

---

### Роль 2: Operation + Handler

**Назначение:**
- инкапсулировать долгоживущее / аудитируемое действие
- обеспечивать retry, cancel, async lifecycle

**Когда использовать:**
- ✅ Операция может занять > 1 сек
- ✅ Нужны retry / cancel / lifecycle
- ✅ Операция критична и должна быть аудитирована
- ✅ Операция синхронизирует внешние API

**Когда НЕ использовать:**
- ❌ Простой read операции (get, list)
- ❌ Быстрые операции (< 100ms)
- ❌ Операции без побочных эффектов

**Где живёт:**
- Operation Manager: `core/operations.py`
- Handlers: `modules/operations/handlers.py` или `modules/{name}/handlers.py`

**Handler может:**
- ✅ Содержать бизнес-логику операции
- ✅ Вызывать Domain Services
- ✅ Публиковать события
- ✅ Работать с outbound adapters (через runtime)
- ✅ Выполнять retry логику
- ✅ Обновлять operation status

**Handler НЕ должен:**
- ❌ Знать HTTP (не парсить body, params)
- ❌ Знать авторизацию (принимает context, если нужно)
- ❌ Вызывать Application Services
- ❌ Знать об HttpRegistry / endpoints

**Регистрация:**
```python
# В module.register():
ops_mgr = runtime.operations
ops_mgr.register_handler("operation.type", handle_operation_type)
```

**Пример (правильно):**
```python
async def handle_device_set_state(params: dict, context: dict) -> dict:
    """Handler: знает бизнес-логику, не знает HTTP"""
    device_id = params["device_id"]
    state = params["state"]
    
    runtime = context["runtime"]
    
    # Вызываю domain service
    old_state = await runtime.service_registry.call(
        "devices.get_state", device_id
    )
    
    # Выполняю бизнес-логику
    if state.get("on") and not old_state.get("on"):
        # Устройство было выключено, теперь включаем
        await runtime.event_bus.publish("device.turned_on", {"device_id": device_id})
    
    # Устанавливаю новое состояние
    result = await runtime.service_registry.call(
        "devices.set_state", device_id, state
    )
    
    return {"success": True, "old_state": old_state, "new_state": result}
```

---

### Роль 3: Domain Service

**Назначение:**
- инкапсулировать чистую бизнес-логику домена
- работать с domain entities и state

**Где живёт:**
- `modules/{domain}/services.py`
- Регистрируется в ServiceRegistry как `{domain}.{action}`

**Примеры имён:**
- `devices.get`
- `devices.set_state`
- `devices.list_mappings`
- `automation.trigger`
- `presence.update`

**Что может:**
- ✅ Содержать бизнес-правила домена
- ✅ Работать с domain entities (Device, User, Automation)
- ✅ Использовать storage через runtime
- ✅ Вызывать другие domain services
- ✅ Выполнять сложную логику состояния

**Что НЕ может:**
- ❌ Знать HTTP
- ❌ Знать авторизацию / ACL
- ❌ Напрямую вызывать external APIs (yandex, oauth)
- ❌ Знать про операции / operations
- ❌ Вызывать Application Services

**Сигнатура:**
```python
async def domain_service(param1, param2, ...) -> Any
```

**Контракт:** Domain Service должен быть **чистой функцией** (при одних входах всегда одинаковый результат).

**Пример (правильно):**
```python
async def domain_devices_set_state(device_id: str, state: dict) -> dict:
    """Domain service: чистая логика"""
    runtime = get_runtime()  # или passed in context
    
    # Получаю текущее состояние
    device = await runtime.storage.get("devices", device_id)
    if not device:
        raise ValueError(f"Device {device_id} not found")
    
    # Применяю бизнес-правило: что можно менять?
    allowed_fields = {"on", "brightness"}
    filtered_state = {k: v for k, v in state.items() if k in allowed_fields}
    
    # Сохраняю
    new_device = {**device, "state": filtered_state, "updated_at": time.time()}
    await runtime.storage.set("devices", device_id, new_device)
    
    return new_device
```

---

## Часть 2: Правила для HTTP (Inbound Adapter)

### Принцип

HTTP это **входящий адаптер**, не use-case.

HTTP handler это **последний уровень адаптации**, не бизнес-логика.

### Что относится к HTTP

**HTTP endpoint:**
- живёт в `adapters/http/`
- или регистрируется через HttpRegistry

**HTTP handler:**
- максимум 20–30 строк
- только: parse → validate → call service → return

**HttpRegistry entry:**
- декларативный (не содержит логики)
- только метаданные: {method, path, service_name}

### Что НЕЛЬЗЯ делать

❌ **Запрещено добавлять FastAPI код в modules/***

```python
# НЕПРАВИЛЬНО (не делать так):
# modules/admin/module.py
@app.post("/admin/v1/devices/{id}/state")
async def set_device_state(id: str, body: dict):
    ...
```

❌ **Запрещено добавлять HttpEndpoint в module.register()**

```python
# НЕПРАВИЛЬНО (не делать так):
# modules/my_feature/module.py
async def register(self):
    # Добавляю endpoint
    self.runtime.http.register(HttpEndpoint(...))
```

### Правильный подход

**Шаг 1: Определить Application Service**
```python
# modules/my_feature/module.py
async def my_feature_do_something(param1, param2):
    # парсю и вызываю
    ...
```

**Шаг 2: Зарегистрировать в ServiceRegistry**
```python
await service_registry.register("my_feature.do_something", my_feature_do_something)
```

**Шаг 3: Добавить HttpRegistry entry**
```python
http_endpoints = [
    HttpEndpoint(
        method="POST",
        path="/my-feature/do-something",
        service="my_feature.do_something"
    )
]
for ep in http_endpoints:
    runtime.http.register(ep)
```

**Шаг 4: HTTP adapter сам создаст handler**

ApiModule читает HttpRegistry и автоматически создаёт FastAPI handler.

---

## Часть 3: Правила для ServiceRegistry

### ServiceRegistry — это RPC, не magic

ServiceRegistry хранит: `Dict[name → function]`

### Регистрация сервисов

**Когда регистрировать:**
- во время module.register()
- ровно один раз за всю жизнь runtime

**Как регистрировать:**
```python
# Базовый сервис
await service_registry.register("name", async_function)

# С ACL (для admin services)
await service_registry.register_with_acl(
    "admin.name",
    async_function,
    admin_only=True
)

# С ACL и политиками
await service_registry.register_with_acl(
    "devices.list",
    async_function,
    resource="device",
    filter_result=True,  # фильтровать результат через ACL
    admin_only=False
)
```

### Сигнатуры функций

**ВАЖНО: сигнатуры могут быть разными**

ServiceRegistry не гарантирует единую сигнатуру. HttpAdapter отвечает за подготовку параметров.

```python
# Функция 1: без параметров
async def admin_v1_runtime() -> dict:
    ...

# Функция 2: с позиционными параметрами
async def devices_get(device_id: str) -> dict:
    ...

# Функция 3: с query параметрами
async def admin_operations_list(limit: int = 100, offset: int = 0) -> dict:
    ...

# Функция 4: с body + params
async def admin_devices_set_state(id: str, body: dict = None) -> dict:
    ...
```

HttpAdapter (`modules/api/module.py`) парсит параметры и передаёт через `**kwargs`.

### Вызов сервиса

```python
result = await service_registry.call("name", *args, **kwargs)
```

**Ответственность вызывающего:**
- передать правильные параметры
- обработать исключение

---

## Часть 4: Decision Tree — Куда класть новый код?

Используй эту таблицу, когда ты пишешь новую фичу.

### Я добавляю новый HTTP endpoint

❓ *"Я хочу создать новый API endpoint"*

**Действие:**
1. Создать Application Service
2. Зарегистрировать в ServiceRegistry
3. Добавить HttpRegistry entry
4. HTTP adapter создаст FastAPI handler

**Файлы:**
- Application Service: `modules/{name}/module.py` или `modules/{name}/services.py`
- HttpRegistry entry: `modules/{name}/module.py` → `register()`

---

### Я добавляю новый admin endpoint

❓ *"Я хочу добавить новый /admin/v1/* endpoint"*

**Действие:**
1. Создать Application Service в AdminModule
2. Зарегистрировать в ServiceRegistry
3. Добавить HttpRegistry entry в AdminModule
4. HTTP adapter создаст FastAPI handler

**Файлы:**
- AdminModule: `modules/admin/module.py`

**Внимание:** AdminModule уже большой (1309 строк). Если добавляешь много новых endpoints, можно разделить на подмодули.

---

### Я реализую долгоживущую операцию

❓ *"Я хочу создать операцию типа 'sync with external API'"*

**Действие:**
1. Создать Handler в `modules/operations/handlers.py`
2. Зарегистрировать в OperationManager
3. Создать Application Service, которая вызывает Operation
4. Добавить HttpRegistry entry для Application Service

**Файлы:**
- Handler: `modules/operations/handlers.py`
- Registration: `modules/admin/module.py` → `register()` (где регистрируются handlers)
- Application Service: `modules/admin/module.py`

---

### Я реализую бизнес-правило домена

❓ *"Я хочу добавить правило 'Device можно менять, если owner'"*

**Действие:**
1. Создать Domain Service в `modules/{domain}/services.py`
2. Зарегистрировать в ServiceRegistry
3. Вызвать из Handler или Application Service

**Файлы:**
- Domain Service: `modules/{domain}/services.py`
- Registration: `modules/{domain}/module.py` → `register()`

---

### Я работаю с внешним API

❓ *"Я хочу интегрировать Slack / Telegram / другой API"*

**Действие:**
1. Создать Outbound Adapter в `adapters/external/{name}/`
2. Создать Domain Service, которая использует adapter
3. Вызвать Domain Service из Handler/Application Service

**Файлы:**
- Adapter: `adapters/external/{name}/client.py`
- Domain Service: `modules/{name}/services.py`
- Registration: `modules/{name}/module.py`

---

### Я работаю с БД / Storage

❓ *"Я хочу сохранить новый тип данных"*

**Действие:**
1. Использовать Storage API через runtime
2. Domain Service содержит логику сохранения
3. Application Service не работает со storage напрямую

**Файлы:**
- Domain Service: `modules/{domain}/services.py`

**Не создавай:**
- Новый Storage Adapter (используй существующий SQLite/PostgreSQL)
- ORM или schema (Storage API это key-value)

---

### Я публикую события

❓ *"Я хочу, чтобы другие модули знали о важном событии"*

**Действие:**
1. Публиковать через EventBus в Handler или Domain Service
2. Другие модули подписываются в своих `register()` методах

**Файлы:**
- Публикация: `modules/{name}/handlers.py` или `services.py`
- Подписка: `modules/{other}/module.py` → `register()`

---

## Часть 5: Anti-Patterns (Запреты)

Это паттерны, которые ЗАПРЕЩЕНЫ для нового кода.

### ❌ Anti-Pattern 1: HTTP Logic в modules/*

```python
# ЗАПРЕЩЕНО:
# modules/my_feature/module.py
async def my_service(request: Request):
    # Работаю напрямую с FastAPI Request
    body = await request.json()
    ...
```

**Почему:** modules не должны знать про HTTP.

**Правильно:** Парсинг HTTP делается в HTTP adapter, потом вызывается service.

---

### ❌ Anti-Pattern 2: Business Logic в Application Service

```python
# ЗАПРЕЩЕНО:
# modules/admin/module.py
async def admin_devices_set_state(id, body):
    device = await runtime.storage.get("devices", id)
    
    # Слишком много логики
    if device["owner_id"] != context.user_id and not context.is_admin:
        if device["shared_with"] and context.user_id not in device["shared_with"]:
            raise ForbiddenError()
        
        # Ещё логика...
        if device.get("locked"):
            raise LockedError()
        
        # И ещё...
        allowed_changes = compute_allowed_changes(device, context)
        new_state = {k: v for k, v in body["state"].items() if k in allowed_changes}
    else:
        new_state = body["state"]
    
    # Сохраняю
    device["state"] = new_state
    await runtime.storage.set("devices", id, device)
    
    return device
```

**Почему:** Application Service это оркестрация, не бизнес-логика.

**Правильно:**
- Application Service: парсит, вызывает operation/handler
- Handler или Domain Service: содержит логику

---

### ❌ Anti-Pattern 3: Direct Storage Access из Application Service

```python
# ЗАПРЕЩЕНО:
async def admin_users_list():
    users = await runtime.storage.list_keys("users")
    return [await runtime.storage.get("users", uid) for uid in users]
```

**Почему:** Application Service не должна знать про storage.

**Правильно:**
```python
async def admin_users_list():
    return await service_registry.call("users.list_all")

# В domain service:
async def domain_users_list_all():
    users = await runtime.storage.list_keys("users")
    return [await runtime.storage.get("users", uid) for uid in users]
```

---

### ❌ Anti-Pattern 4: Operation Handler, который знает HTTP

```python
# ЗАПРЕЩЕНО:
# modules/operations/handlers.py
async def handle_sync_yandex(params, context):
    # Handler знает про HTTP
    request = context["request"]
    if request.query_params.get("async"):
        # Запускаю асинхронно
        ...
```

**Почему:** Handler не должен знать про HTTP.

**Правильно:** Application Service парсит HTTP параметры и передаёт их операции как `params`.

---

### ❌ Anti-Pattern 5: Вложенные Application Services

```python
# ЗАПРЕЩЕНО:
async def admin_feature_complex():
    # Вызываю другой admin service
    step1 = await service_registry.call("admin.devices.get", device_id)
    step2 = await service_registry.call("admin.devices.set_state", ...)
    step3 = await service_registry.call("admin.devices.list", ...)
    ...
```

**Почему:** Application Services должны быть независимы.

**Правильно:**
- Если нужна сложная оркестрация → операция + handler
- Если нужны многошаговые операции → Handler, который вызывает domain services

---

### ❌ Anti-Pattern 6: "Helper Service" без роли

```python
# ЗАПРЕЩЕНО:
await service_registry.register("helper.parse_json", lambda x: json.loads(x))
await service_registry.register("helper.is_admin", lambda ctx: ctx.is_admin)
```

**Почему:** ServiceRegistry это не утилитарный модуль. Каждый сервис должен иметь чёткую роль.

**Правильно:** Используй обычные функции / utils, не регистрируй в ServiceRegistry.

---

### ❌ Anti-Pattern 7: Новые модули без domain logic

```python
# ЗАПРЕЩЕНО:
# modules/my_helpers/
# — просто набор утилит, нет доменной логики
```

**Почему:** Модули это domain-driven. Если нет домена → это не модуль.

**Правильно:** Или добавляй логику в существующий модуль, или создавай новый домен с бизнес-смыслом.

---

## Часть 6: Чеклист для Code Review

Используй этот чеклист, когда делаешь код-ревью нового кода.

### ✅ Application Service

- [ ] Функция <= 40 строк
- [ ] Не содержит сложную бизнес-логику (не > 2 уровней if)
- [ ] Не работает напрямую со storage
- [ ] Не вызывает другие application services
- [ ] Парсит HTTP параметры и делегирует работу
- [ ] Возвращает результат, пригодный для HTTP

### ✅ Operation Handler

- [ ] Регистрирован в OperationManager
- [ ] НЕ знает про HTTP (нет request, response, params)
- [ ] Вызывает Domain Services, не Application Services
- [ ] Может публиковать события
- [ ] Может выполнять retry логику
- [ ] Имеет информацию о context (runtime)

### ✅ Domain Service

- [ ] Зарегистрирован в ServiceRegistry
- [ ] НЕ знает про HTTP
- [ ] НЕ знает про авторизацию
- [ ] Содержит бизнес-правила домена
- [ ] Может вызывать другие domain services
- [ ] Работает с storage через runtime

### ✅ HttpRegistry Entry

- [ ] Имеет правильный service_name (существует в ServiceRegistry)
- [ ] path начинается с `/`
- [ ] method в списке (GET, POST, PUT, DELETE, PATCH)
- [ ] description не пусто

### ✅ Общее

- [ ] Нет импортов между modules напрямую (только через runtime API)
- [ ] Нет новых dependencies без обоснования
- [ ] Нет "magic" кода, всё явное
- [ ] Логирование на нужных уровнях
- [ ] Error handling правильный (не ловим Exception)

---

## Связь с предыдущей документацией

**Этот документ дополняет, не заменяет:**

- [01-ARCHITECTURE.md](01-ARCHITECTURE.md) — архитектурные инварианты (это документ)
- [04-CORE-RUNTIME-CONTRACT.md](04-CORE-RUNTIME-CONTRACT.md) — контракт Core
- [09-APPLICATION-USE-CASE-MODEL.md](09-APPLICATION-USE-CASE-MODEL.md) — как система работает сейчас

**Иерархия:**
```
01-ARCHITECTURE.md (principles)
  ↓
09-APPLICATION-USE-CASE-MODEL.md (current state)
  ↓
10-DEVELOPMENT-RULES-AND-GUARDRAILS.md (THIS — rules for new code)
```

**Что делать, если правила противоречат документации?**

1. Сначала читай 01-ARCHITECTURE
2. Если противоречие остаётся → обсуди с архитекторами
3. Измени документацию, если необходимо

---

## Резюме

### Три роли, три ответственности

| Роль | Назначение | Может | НЕ может |
|------|-----------|--------|---------|
| **Application Service** | оркестрация | парсить HTTP, вызывать operations | содержать logic, работать со storage |
| **Handler** | execute operation | call domain services, publish events | знать HTTP, знать auth |
| **Domain Service** | business logic | содержать logic, использовать storage | знать HTTP, работать напрямую с external APIs |

### Три места

| Что | Где | Регистрация |
|-----|-----|-------------|
| HTTP endpoint | HttpRegistry | во время module.register() |
| Application Service | ServiceRegistry | во время module.register() |
| Handler | OperationManager | во время module.register() |

### Один принцип

> **Разделение ответственности по слоям: HTTP → Application → Operation/Handler → Domain**

Каждый слой знает только то, что ниже. Никогда наоборот.

---

## Быстрая помощь

### Я новичок. С чего начать?

1. Прочитай [09-APPLICATION-USE-CASE-MODEL.md](09-APPLICATION-USE-CASE-MODEL.md) (поймёшь как работает)
2. Найди похожий код в `modules/` или `modules/admin/`
3. Следуй этому паттерну
4. Используй чеклист из Части 6

### Я не уверен, куда класть код

1. Посмотри таблицу в Части 4
2. Ответь на вопрос ❓
3. Если всё ещё не ясно → обсуди с командой

### Я вижу нарушение anti-pattern

1. Отметь в code review
2. Предложи правильный паттерн
3. Если это старый код → не требуй изменений (это легаси)
4. Если это новый код → требуй исправлений

---

## История документа

| Версия | Дата | Статус | Комментарий |
|--------|------|--------|------------|
| 0.1.0 | TBD | Draft | Initial version (before review) |
| 1.0.0 | 2026-01-31 | Active | Approved and binding |

---

## Контакты

Вопросы по этому документу:

- 📋 Architecture-related → обсудить в #architecture
- 🔧 Implementation-related → code review
- 📝 Document updates → pull request с обоснованием
