# Plugin SDK v1

Внешний контракт плагина. Плагин пишется, импортируя только `sdk`. Без ссылок на admin, ui, product api, `core/*`, `modules/*`, `app/*`.

---

## 1. Что такое плагин

Плагин — опциональное расширение runtime. Наследует `sdk.BasePlugin`, реализует `metadata` и lifecycle (on_load, on_start, on_stop, on_unload). Загружается только через manifest (plugin.json). Не знает Core internals; получает opaque `runtime` (PluginRuntime).

### 1.1. Канонические правила (hard constraints)

- Плагины **НЕ импортируют** из `core`, `modules`, `app`, `plugins`.
- Плагины **НЕ получают** полный `CoreRuntime`.
- Взаимодействие с системой — **только** через публичные методы `BasePlugin`.
- Разрешённые каналы коммуникации:
  - **Сервисы** — `call_service`, `register_service` (через `BasePlugin`, с ACL/policy)
  - **События** — `publish_event`, `subscribe_event` (через `BasePlugin`)
  - **Операции** — `register_operation_handler` (через `BasePlugin`)
  - **Storage** — `storage_get/set/delete/list_keys` (через `BasePlugin`, с policy)
  - **Capabilities** — зависимости по capability-id, не по имени плагина
- CI guard запрещает `core.*`, `modules.*`, `app.*` импорты из `plugins/*`.

---

## 2. Что плагин МОЖЕТ

- Регистрировать сервисы: `await self.register_service(name, func)`
- Регистрировать handlers операций: `self.register_operation_handler(op_type, handler)`
- Объявлять capabilities в metadata: `capabilities_provided`, `capabilities_required`
- Подписываться на события: `await self.subscribe_event(name, handler)` / публиковать `await self.publish_event(...)`
- Читать/писать storage: `await self.storage_get/set/delete/list_keys(...)`
- Регистрировать HTTP endpoints: **только** через `self.register_http_endpoint(HttpEndpoint(...))` (facade + ACL/policy)
- Вызывать сервисы: `await self.call_service(name, *args, **kwargs)`

---

## 3. Что плагин НЕ МОЖЕТ

- Регистрировать HTTP endpoints напрямую через внутренний `HttpRegistry`.
- Трогать admin / inspector
- Вызывать другие плагины напрямую (только через сервисы или capability)
- Управлять своим lifecycle (только реагировать на вызовы Core)
- Импортировать из `core`, `modules`, `plugins`, `app` (только `sdk`)
- Использовать `self.context` / `self.context.*` напрямую (это core-internals). Используйте только методы `BasePlugin`.
- Использовать `runtime.*` / `self.runtime.*` напрямую (включая `runtime.api`) — это core-internals.
- Использовать `inspect` / frame-интроспекцию (`inspect.currentframe`, `f_locals`, `f_globals`) в plugin-слое.

---

## 4. PluginRuntime — минимальный контракт

Публичная поверхность `BasePlugin` — это единственный API плагина. `runtime` — opaque proxy:

| Категория | Методы `BasePlugin` |
|-----------|---------------------|
| **Services** | `register_service`, `call_service`, `has_service` |
| **Events** | `subscribe_event`, `unsubscribe_event`, `publish_event` |
| **Operations** | `register_operation_handler` |
| **Storage** | `storage_get`, `storage_set`, `storage_delete`, `storage_list_keys` |
| **HTTP** | `register_http_endpoint` (через facade + ACL/policy) |
| **Lifecycle** | `on_load`, `on_start`, `on_stop`, `on_unload` |

---

## 5. Lifecycle

| Метод     | Вызывает | Когда использовать |
|----------|-----------|---------------------|
| on_load  | Core      | Регистрация сервисов, capabilities, operations handlers |
| on_start | Core      | Фоновые задачи, подписки на события |
| on_stop  | Core      | Отмена фоновых задач |
| on_unload| Core      | Очистка ресурсов |

Порядок: on_load → on_start → on_stop → on_unload. Плагин не вызывает их сам.

---

## 6. Capabilities

- Capability — обещание поведения (строка, например `"oauth:yandex"`).
- capability ≠ plugin. Плагин зависит от capability по ID, не от имени плагина.
- В metadata: `capabilities_provided`, `capabilities_required` (списки строк).
- SDK не содержит registry; Core владеет реестром.

---

## 7. Operations

- Плагин регистрирует handler: `self.register_operation_handler(op_type, async_handler)`.
- Handler получает params (dict), возвращает результат (dict или что угодно).
- Тип операции — строка (например `"example.ping"`). Core диспетчеризует по типу.
- **At-least-once / dedup** (как Core избегает двойного выполнения при повторах событий и рестартах): `docs/adr/001-dedup-at-least-once-contract.md`, `docs/event_contracts/operation_ready.md`. Обработчики с side effects — **идемпотентные** относительно повторных доставок.
- **Поставить операцию в очередь worker:** `await self.publish_operation_ready(operation_id)` (или `build_operation_ready_payload` + `publish_event`, если нужен полный контроль). Константа типа: `from sdk import OPERATION_READY_EVENT_TYPE`.

---

## 8. Миграция: было → стало

### Импорты

```python
# ❌ БЫЛО (запрещено):
from core.runtime.runtime import CoreRuntime
from core.service.registry import ServiceRegistry
from core.messaging import InMemoryEventBus
from modules.* import ...

# ✅ СТАЛО:
from sdk.plugin_ext import BasePlugin, PluginMetadata
from sdk import HttpEndpoint, EndpointAuthConfig, ServiceAuthConfig
from sdk import OPERATION_READY_EVENT_TYPE, build_operation_ready_payload
```

### Доступ к runtime

```python
# ❌ БЫЛО:
runtime.kernel_context, runtime.plugins, runtime.module_manager
runtime.service_registry.register(...)

# ✅ СТАЛО:
await self.register_service(name, fn)      # с ACL/policy
await self.call_service(name, *args, **kwargs)
await self.storage_get(namespace, key)
await self.publish_event(event_type, payload)
self.register_operation_handler(op_type, handler)
```

### Регистрация HTTP

```python
# ❌ БЫЛО:
runtime.http.register(HttpEndpoint(...))

# ✅ СТАЛО:
self.register_http_endpoint(HttpEndpoint(..., auth_config=EndpointAuthConfig(...)))
```

### Storage

```python
# ❌ БЫЛО:
runtime.storage.get/set(...)

# ✅ СТАЛО:
await self.storage_get(namespace, key)
await self.storage_set(namespace, key, value)
await self.storage_delete(namespace, key)
```

---

## 9. Чеклист перед on_load

- [ ] Класс наследует `sdk.BasePlugin`
- [ ] Реализован `metadata` → `sdk.PluginMetadata`
- [ ] Нет импортов из `core` / `modules` / `plugins` / `app`
- [ ] Все сервисы через `self.register_service` (не через `runtime.service_registry`)
- [ ] HTTP endpoints через `self.register_http_endpoint` с `auth_config`
- [ ] Зависимости от других плагинов только через capabilities
- [ ] CI guard проходит (`tests/test_plugin_sdk_imports_guard.py`)

---

Эталонный пример: `examples/example_plugin/`.
