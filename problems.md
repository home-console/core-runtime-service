# Critical Problems in Core & Modules

_Дата анализа: 2026-03-29 (обновлено)_

---

## ✅ ИСПРАВЛЕНО

| Проблема | Статус |
|----------|--------|
| `client_manager`: неверные импорты (`core.base_plugin`, `core.http_registry`) | ✅ Исправлено |
| `PluginRuntimeFacade` не имел `register_service` / `unregister_service` | ✅ Исправлено |
| `ProviderMetadata`: `timeouts`/`capabilities` без `Optional[...]` | ✅ Исправлено |
| Стейл-импорты после рефакторинга путей (`core/auth_contextvars`, etc.) | ✅ Нет в кодовой базе |
| `client_manager` `on_start`: `No module named 'app.core'` (namespace конфликт с корневым `app/`) | ✅ Исправлено |
| `yandex_smart_home`: `use_real_api_disabled` создавал ERROR-операции внутри `operation()` контекста → OperationsWorker ретраил бесконечно | ✅ Исправлено |

---

## 🔴 КРИТИЧЕСКИЕ ПРОБЛЕМЫ

### 1. `PluginRuntimeFacade` не проксирует `register_http` и `register_operation_handler`

**Файл:** `core/kernel/plugin_runtime_facade.py`

**Проблема:**

`BasePlugin.register_http_endpoint()` вызывает:
```python
runtime_api = self._runtime_api()   # → PluginRuntimeFacade
runtime_api.register_http(endpoint) # ← AttributeError: нет метода
```

`BasePlugin.register_operation_handler()` — аналогично:
```python
runtime_api.register_operation_handler(op_type, handler)  # ← AttributeError
```

Метод есть только в `PluginAPI` (доступен как `facade.api`), но сам фасад его **не проксирует**.

**Затронутые плагины (упадут в `on_load`):**
- `plugins/client_manager/plugin.py` — 6 вызовов `register_operation_handler` + `register_http_endpoint`
- `plugins/yandex_device_auth/plugin.py` — 6 вызовов `register_http_endpoint`
- `plugins/oauth_yandex/plugin.py` — 1 вызов `register_http_endpoint`
- `plugins/test/websocket_test_plugin.py` — 1 вызов `register_http_endpoint`

**Решение** — добавить в `PluginRuntimeFacade`:
```python
def register_http(self, endpoint: Any) -> None:
    self.api.register_http(endpoint)

def register_operation_handler(self, op_type: str, handler: Any) -> None:
    self.api.register_operation_handler(op_type, handler)
```

---

### 2. `self.runtime.kernel_context` без None-guard в 30+ местах

**Файлы:** `modules/request_logger/http_client.py`, `modules/devices/module.py`, `modules/presence/module.py`, `modules/execution/module.py`, `modules/product_api/module.py`, `modules/admin/*`, `modules/api/route_binding.py`, `modules/operations/handlers.py`

**Проблема:**

`kernel_context` объявлен как `Optional[KernelContext]` в `CoreRuntime.__init__`:
```python
self.kernel_context: Optional[KernelContext] = KernelContext(...)
```

Но 30+ мест обращаются к нему **без проверки на None**:
```python
services = self.runtime.kernel_context.get_service("service_registry")  # NoneType crash если kernel_context=None
ctx = self.runtime.kernel_context  # аналогично
await self.runtime.kernel_context.emit(...)  # аналогично
```

**Почему не падает сейчас:** `kernel_context` всегда инициализируется в конструкторе. Но если `CoreRuntime` будет переработан или использован в тестах без полного `__init__` — 30+ точек упадут.

**Дополнительный риск:** `self.runtime` в `RuntimeModule` может быть `None` (см. хрупкий контракт `__init__`). Тогда `self.runtime.kernel_context` падает уже на первом `.` — `AttributeError: 'NoneType' object has no attribute 'kernel_context'`.

**Решение:** Либо убрать `Optional` (сделать `kernel_context` обязательным полем), либо добавить `assert self.runtime is not None` в `RuntimeModule` там где используется, либо стандартизировать все модули на `self.context.services` вместо `self.runtime.kernel_context.get_service(...)`.

---

### 3. Хрупкий контракт `RuntimeModule.__init__` — `self.runtime = None`

**Файл:** `core/runtime_module.py`

**Проблема:**

```python
if isinstance(runtime_or_context, RuntimeContext):
    self.context = runtime_or_context
    self.runtime = None  # ← устанавливается в None
    return

self.runtime = runtime_or_context
```

18+ модулей вызывают `self.runtime.kernel_context.get_service(...)`, предполагая что `self.runtime` не None. Сейчас безопасно только потому, что `ModuleManager._create_module_instance()` всегда передаёт полный `CoreRuntime`. Один рефактор или тест — и всё упадёт.

**Конкретные файлы (вызовы `self.runtime.*`):**
- `modules/request_logger/http_client.py` — 5 точек
- `modules/presence/module.py` — 2 точки
- `modules/execution/module.py` — 2 точки
- `modules/devices/module.py` — 1 точка
- `modules/product_api/module.py` — 1 точка

**Решение:** Стандартизировать все модули на `self.context.services` / `self.context.event_bus`. Убрать ветку `RuntimeContext` из `__init__` или добавить `assert self.runtime is not None` перед каждым обращением.

---

## 🟡 УМЕРЕННЫЕ ПРОБЛЕМЫ

### 4. Два каталога `client_manager` — неоднозначность загрузки

**Файлы:**
- `plugins/client-manager-plugin/` — standalone git repo, загружается с `sys.path.insert`
- `plugins/client_manager/` — in-process пакет, импортируется как `plugins.client_manager`

Оба имеют `plugin.json` с `"name": "client_manager"`. При discovery манифестов могут конфликтовать — `PluginManager` загрузит только один, второй будет молча проигнорирован или перезаписан.

**Решение:** Определиться с одной реализацией и удалить дубль. Либо дать разные `"name"` в `plugin.json`.

---

### 5. Несогласованный паттерн доступа к сервисам

В модулях используется два паттерна:
```python
# Безопасный (через context):
self.context.services.call("service_name")

# Хрупкий (через runtime → kernel_context):
self.runtime.kernel_context.get_service("service_registry").call("service_name")
```

Второй паттерн требует двух не-None объектов (`self.runtime` и `kernel_context`) и длиннее. Везде можно использовать первый.

---

### 6. `network_scanner` — отсутствует пакет `netifaces`

Плагин не загружается (`No module named 'netifaces'`). Пакет нужно установить в окружение:
```bash
pip install netifaces
```
Либо обернуть импорт в try/except и отключить функциональность gracefully, если пакет недоступен.

---

### 7. `ProviderMetadata` — мутабельные дефолты через `__post_init__` (anti-pattern)

**Файл:** `core/capability/protocol.py`

Тип теперь корректный (`Optional[Dict]`, `Optional[List]`), но инициализация через `__post_init__` создаёт путаницу — поле объявлено как `Optional`, а фактически никогда не остаётся `None` после создания экземпляра. Рекомендуется:

```python
from dataclasses import field

timeouts: Dict[str, float] = field(default_factory=dict)
capabilities: List[str] = field(default_factory=list)
```

И убрать `__post_init__` (или оставить только для backward-compat валидации).
