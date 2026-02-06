# Plugin SDK v0

Внешний контракт плагина. Плагин пишется, импортируя только `sdk`. Без ссылок на admin, ui, product api.

---

## 1. Что такое плагин

Плагин — опциональное расширение runtime. Наследует `sdk.BasePlugin`, реализует `metadata` и lifecycle (on_load, on_start, on_stop, on_unload). Загружается только через manifest (plugin.json). Не знает Core internals; получает opaque `runtime` (PluginRuntime).

---

## 2. Что плагин МОЖЕТ

- Регистрировать сервисы: `runtime.service_registry.register(name, func)`
- Регистрировать handlers операций: `runtime.operations.register_handler(type, handler)`
- Объявлять capabilities в metadata: `capabilities_provided`, `capabilities_required`
- Подписываться на события: `runtime.event_bus.subscribe(name, handler)`
- Читать/писать storage: `runtime.storage.get/set/list_keys`
- Читать/писать state: `runtime.state.get/set/list_keys`

---

## 3. Что плагин НЕ МОЖЕТ

- Регистрировать HTTP endpoints (это делает модуль/адаптер по HttpRegistry)
- Трогать admin / inspector
- Вызывать другие плагины напрямую (только через `runtime.service_registry` или capability)
- Управлять своим lifecycle (только реагировать на вызовы Core)
- Импортировать из `core`, `modules`, `plugins`, `app` (только `sdk`)

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

- Плагин регистрирует handler: `runtime.operations.register_handler(op_type, async_handler)`.
- Handler получает params (dict), возвращает результат (dict или что угодно).
- Тип операции — строка (например `"example.ping"`). Core диспетчеризует по типу.

---

## 7. Чеклист перед on_load

- [ ] Класс наследует `sdk.BasePlugin`
- [ ] Реализован `metadata` → `sdk.PluginMetadata`
- [ ] Нет импортов из core / modules / plugins / app
- [ ] Нет регистрации HTTP, нет обращений к admin/inspector
- [ ] Зависимости от других плагинов только через capabilities (или dependencies в manifest)

---

Эталонный пример: `examples/example_plugin/`.
