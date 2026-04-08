# Plugin SDK v0

Внешний контракт плагина. Плагин пишется, импортируя только `sdk`. Без ссылок на admin, ui, product api.

---

## 1. Что такое плагин

Плагин — опциональное расширение runtime. Наследует `sdk.BasePlugin`, реализует `metadata` и lifecycle (on_load, on_start, on_stop, on_unload). Загружается только через manifest (plugin.json). Не знает Core internals; получает opaque `runtime` (PluginRuntime).

---

## 2. Что плагин МОЖЕТ

- Регистрировать сервисы: `await self.register_service(name, func)`
- Регистрировать handlers операций: `self.register_operation_handler(op_type, handler)`
- Объявлять capabilities в metadata: `capabilities_provided`, `capabilities_required`
- Подписываться на события: `await self.subscribe_event(name, handler)` / публиковать `await self.publish_event(...)`
- Читать/писать storage: `await self.storage_get/set/delete/list_keys(...)`
- Читать/писать state: **legacy surface**. Новый код **не должен** использовать `self.context.*` (включая `self.context.state`) — предпочитайте storage и события.

---

## 3. Что плагин НЕ МОЖЕТ

- Регистрировать HTTP endpoints напрямую через внутренний `HttpRegistry` (это делает модуль/адаптер).
- Трогать admin / inspector
- Вызывать другие плагины напрямую (только через `runtime.service_registry` или capability)
- Управлять своим lifecycle (только реагировать на вызовы Core)
- Импортировать из `core`, `modules`, `plugins`, `app` (только `sdk`)
- Использовать `self.context` / `self.context.*` напрямую (это core-internals). Используйте только методы `BasePlugin`.
- Использовать `runtime.*` / `self.runtime.*` напрямую (включая `runtime.api`) — это core-internals.
- Использовать `inspect` / frame-интроспекцию (`inspect.currentframe`, `f_locals`, `f_globals`) в plugin-слое.

Примечание: если продуктовая политика разрешает HTTP из plugin-слоя, это делается **только** через хелпер `BasePlugin.register_http_endpoint(...)` (facade/ACL/policy), а не через прямой доступ к внутренним объектам runtime.

---

## 4. Lifecycle

| Метод     | Вызывает | Когда использовать |
|----------|-----------|---------------------|
| on_load  | Core      | Регистрация сервисов, capabilities, operations handlers |
| on_start | Core      | Фоновые задачи, подписки на события |
| on_stop  | Core      | Отмена фоновых задач |
| on_unload| Core      | Очистка ресурсов |

Порядок: on_load → on_start → on_stop → on_unload. Плагин не вызывает их сам.

---

## 5. Capabilities

- Capability — обещание поведения (строка, например `"oauth:yandex"`).
- capability ≠ plugin. Плагин зависит от capability по ID, не от имени плагина.
- В metadata: `capabilities_provided`, `capabilities_required` (списки строк).
- SDK не содержит registry; Core владеет реестром.

---

## 6. Operations

- Плагин регистрирует handler: `self.register_operation_handler(op_type, async_handler)`.
- Handler получает params (dict), возвращает результат (dict или что угодно).
- Тип операции — строка (например `"example.ping"`). Core диспетчеризует по типу.
- **At-least-once / dedup** (как Core избегает двойного выполнения при повторах событий и рестартах): `docs/adr/001-dedup-at-least-once-contract.md`, `docs/event_contracts/operation_ready.md`. Обработчики с side effects — **идемпотентные** относительно повторных доставок.
- **Поставить операцию в очередь worker:** `await self.publish_operation_ready(operation_id)` (или `build_operation_ready_payload` + `publish_event`, если нужен полный контроль). Константа типа: `from sdk import OPERATION_READY_EVENT_TYPE`.

---

## 7. Чеклист перед on_load

- [ ] Класс наследует `sdk.BasePlugin`
- [ ] Реализован `metadata` → `sdk.PluginMetadata`
- [ ] Нет импортов из core / modules / plugins / app
- [ ] Нет регистрации HTTP, нет обращений к admin/inspector
- [ ] Зависимости от других плагинов только через capabilities (или dependencies в manifest)

---

Эталонный пример: `examples/example_plugin/`.
