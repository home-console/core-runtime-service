# ТЗ: Стабильный Plugin SDK (v1) и миграция существующих плагинов

Дата: 2026-04-03  
Репозиторий: `core-runtime-service`

## 0. Цель

Сделать **стабильную границу** между `plugins/*` и внутренностями `core/*`/`modules/*`/`app/*`.

Итог: плагин пишется, импортируя **только** `sdk` (и стандартную библиотеку/свои зависимости), не зависит от структуры `core/`. Рефакторинг `core/` не ломает плагины.

## 1. Текущее состояние (что уже есть)

В репозитории уже присутствуют:

- `sdk/*` — базовый контракт (v0) + README с правилами.
- `core/kernel/plugin_runtime_facade.py` — `PluginRuntimeFacade`: ограниченный facade, похожий на то, что нужно плагинам.

Проблема: **нет формального “enforcement”** (CI guard), и плагины продолжают импортировать `core.*` напрямую.

## 2. Объём работ (scope)

### Входит

- Формализовать **SDK v1** как единственную публичную точку импорта для плагиновs.
- Определить **контракты** поверхностей runtime, которые разрешены плагину.
- Обеспечить **backward-compat** (по возможности) через facade/adapter слой.
- Добавить **CI guard**: запрет прямых импортов `core.*`, `modules.*`, `app.*` из `plugins/*`.
- Составить **матрицу миграции** для существующих плагинов: что и как переписывать.

### Не входит (в эту волну)

- Переписывание бизнес-логики плагинов/домена.
- Полная переработка plugin.json схемы (может быть отдельной задачей).
- Перевод модулей на SDK (SDK предназначен только для plugins).

## 3. Канонические правила (hard constraints)

- Плагины **НЕ импортируют** из `core`, `modules`, `app`, `plugins`.
- Плагины **НЕ получают** полный `CoreRuntime`.
- Плагины работают через **opaque runtime**, совместимый с `sdk.context.PluginRuntime`.
- Разрешённая коммуникация между плагинами и системой — через:
  - `service_registry` (call/register) + ACL/policy
  - `operations` (register handler / enqueue / inspect)
  - `event_bus` (publish/subscribe)
  - `storage/state` (через proxy/ports)
  - `capabilities` (зависимости по capability-id, а не по имени плагина)

## 4. SDK v1 — контракт и публичные поверхности

### 4.1. Пакет `sdk`

`sdk` должен стать **единственным публичным API** для plugins:

- `sdk.BasePlugin`
- `sdk.PluginMetadata`
- `sdk.PluginRuntime` (Protocol)
- базовые типы: `CapabilityId`, security helpers (sanitizers), lifecycle utils.

**Запрет**: любые прямые импорты из `core/*` (кроме core→sdk, если нужно для typing).

### 4.2. `PluginRuntime` (минимальный контракт)

Требования к runtime, который получает плагин:

- **service API**:
  - `await runtime.call_service(name, *args, **kwargs)`
  - `await runtime.has_service(name)`
  - `runtime.service_registry` (для legacy, но целевой путь — через методы/`runtime.api`)
- **events**:
  - `await runtime.publish_event(event_type, payload)`
  - `runtime.event_bus.subscribe(event_type, handler)` (и `unsubscribe`, если доступно)
- **operations**:
  - `runtime.operations.register_handler(op_type, handler)` (или через `runtime.api.register_operation_handler`)
- **storage/state**:
  - `await runtime.storage_get(namespace, key)`
  - `await runtime.storage_set(namespace, key, value)`
  - `await runtime.storage_delete(namespace, key)`
  - (опционально) `list_keys`
- **api façade**:
  - `runtime.api` (PluginAPI) — канонический слой регистрации сервисов/http/operation handlers

Примечание: сейчас `sdk/context.py` содержит Protocol, а `core/kernel/plugin_runtime_facade.py` содержит реализацию facade. Цель v1 — **свести их** и гарантировать совместимость.

### 4.3. Запреты (SDK-level)

- Плагин **не регистрирует HTTP** напрямую (если политика продукта запрещает) — либо:
  - разрешить только через `runtime.api.register_http(endpoint)` с policy/ACL, либо
  - полностью запретить и оставить HTTP только на уровне modules.

Решение должно быть единым и закреплено тут. На текущий момент правило такое:
- **нельзя** регистрировать HTTP через прямой доступ к внутреннему `HttpRegistry`/runtime internals;
- **можно только через** `runtime.api.register_http(...)`, если app-layer политика это разрешает (и есть enforcement/ACL/policy).

## 5. Runtime-side: адаптер/фасад для плагинов

### 5.1. Канонический объект: `PluginRuntimeFacade` (или `sdk.runtime.PluginRuntimeImpl`)

Нужно выбрать 1 каноническую реализацию, которую Core отдаёт плагину:

- Вариант A: оставить `core/kernel/plugin_runtime_facade.py::PluginRuntimeFacade`, довести его до строгого соответствия `sdk.PluginRuntime` и расширять только его.
- Вариант B: переместить реализацию в `sdk/` (как `sdk/runtime_impl.py`), а `core` только собирает зависимости и отдаёт instance.

Оба варианта допустимы, но **важно**: публичный импорт для плагина остаётся `sdk.*`.

### 5.2. Изоляция и policy

Facade обязан работать поверх proxy/ports:

- `ServiceProxy` (allowed_services из manifest + runtime defaults)
- `StorageProxy` (namespaces allowlist)
- (опционально) `HttpProxy` (если разрешаем плагинам регать HTTP)

## 6. Миграция: “ситуации, которые надо переписывать”

Ниже — практическая матрица для правок в существующих плагинах.

### 6.1. Импорты

**Сейчас (плохо):**

- `from core.runtime.runtime import CoreRuntime`
- `from core.service.registry import ServiceRegistry`
- `from core.messaging import InMemoryEventBus`
- `from modules.* import ...`

**Должно стать (хорошо):**

- `from sdk.plugin_ext import BasePlugin, PluginMetadata`
- `from sdk.context import PluginRuntime` (только typing/Protocol)
- всё взаимодействие с системой — через `self.runtime` (facade).

### 6.2. Доступ к runtime “внутрянке”

**Сейчас:**

- `runtime.kernel_context`, `runtime.plugins`, `runtime.module_manager`, `runtime.plugin_manager`
- прямой доступ к `runtime.services.*` (внутренние компоненты)

**Должно:**

- только `runtime.call_service / publish_event / storage_* / operations / api`.

### 6.3. Регистрация/вызов сервисов

**Сейчас:**

- `runtime.service_registry.register(...)`
- `runtime.service_registry.call(...)`

**Должно:**

- регистрация: `await runtime.api.register_service(name, fn, ...)` (чтобы enforcement/ACL/owner-инъекция были едины)
- вызов: `await runtime.call_service(name, ...)` (или `runtime.api.call_service`)

### 6.4. Events и payload contract

События должны иметь единый payload-shape:

- `payload["id"]` (event id)
- `payload["type"]` (event type)

Плагин не должен предполагать, что “typed vs simple handler” различаются по форме payload.

### 6.5. Storage/state

**Сейчас:**

- `runtime.storage.get/set` напрямую

**Должно:**

- предпочтительно `runtime.storage_get/set/delete/list_keys`, чтобы можно было централизовать policy/observability.

### 6.6. Operations

**Сейчас:**

- прямые импорты моделей/менеджеров из `core.operations.*`

**Должно:**

- регистрация: `runtime.api.register_operation_handler(op_type, handler)`
- enqueue/call: через `runtime.operations` facade (контракт должен быть описан в SDK).

## 7. CI guard (enforcement)

Нужен автоматический запрет “плагин импортирует внутренности”:

- Проверять все файлы в `plugins/**.py` (кроме `plugins/test/*`, если решим их исключить) на импорты:
  - `core`
  - `modules`
  - `app`
  - `plugins` (кроме `plugins.__init__` при необходимости)
- Исключение: разрешить `from sdk ...` и стандартную библиотеку.

Реализация:

- `scripts/validate_plugin_sdk_imports.py` (AST-based, без grep), вызывается в CI/pytest.

## 8. План внедрения (итерациями)

### Итерация 1 — “документ + guard + совместимость”

- Обновить SDK README до v1 и устранить противоречие по HTTP (разрешено/запрещено).
- Довести `PluginRuntimeFacade` до строгого соответствия `sdk.PluginRuntime`.
- Добавить CI guard.
- Мигрировать 1–2 “эталонных” плагина (например `plugins/test/example_plugin.py`) на чистый `sdk`.

### Итерация 2 — “массовая миграция”

- Пройтись по `plugins/*` и убрать импорты `core.*`.
- Везде заменить “небезопасные” поверхности runtime на facade calls.

### Итерация 3 — “ужесточение”

- Включить guard в “обязательный” режим (fail build).
- По возможности удалить legacy пути (где это безопасно).

## 9. Definition of Done (DoD)

- `plugins/*` (production plugins) **не импортируют** `core/modules/app`.
- Все плагины используют `sdk.BasePlugin` и `sdk.PluginMetadata`.
- Есть CI guard, который ломает сборку при нарушениях.
- Есть минимум один “reference plugin” как пример.
- Тесты проходят.

## 10. Открытые решения (нужно выбрать до массовой миграции)

1) **HTTP для плагинов**: запрещаем полностью или разрешаем через `runtime.api.register_http()`?  
2) **Куда живёт реализация runtime**: в `core/*` (facade) или в `sdk/*` (impl)?  
3) **Что делать с `plugins/test/*`**: исключить из guard или тоже мигрировать?

