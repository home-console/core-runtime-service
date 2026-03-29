# Critical Problems in Core & Modules

_Дата анализа: 2026-03-29_

---

## КРИТИЧЕСКИЕ ПРОБЛЕМЫ

### 1. Хрупкий контракт `RuntimeModule.__init__` — потенциальный NoneType crash

**Файл:** `core/runtime_module.py`

**Проблема:**

```python
self.runtime: SupportsContext | None

if isinstance(runtime_or_context, RuntimeContext):
    self.context = runtime_or_context
    self.runtime = None  # <-- устанавливается в None
    return

self.runtime = runtime_or_context
```

Контракт допускает передачу либо `RuntimeContext`, либо полного runtime-объекта.
При передаче `RuntimeContext` поле `self.runtime = None`.

**Но 18+ модулей вызывают:**

```python
services = self.runtime.kernel_context.get_service("service_registry")  # упадёт если runtime is None
```

**Затронутые модули:**
- `modules/request_logger/module.py`
- `modules/logger/module.py`
- `modules/admin/module.py`
- `modules/auth/module.py`
- `modules/agent/module.py`
- `modules/execution/module.py`
- и другие (~18 мест)

**Почему не падает сейчас:** `ModuleManager._create_module_instance()` всегда передаёт полный `CoreRuntime`, никогда `RuntimeContext`. Но при рефакторинге или добавлении тестов — упадёт.

**Решение:** Либо убрать RuntimeContext из `__init__`, либо добавить guard-проверки во все модули, либо везде использовать `self.context.services`.

---

### 2. Некорректные type annotations в `ProviderMetadata`

**Файл:** `core/capability/protocol.py` (строки ~152-153)

**Проблема:**

```python
@dataclass
class ProviderMetadata:
    timeouts: Dict[str, float] = None    # тип Dict, значение None
    capabilities: List[str] = None       # тип List, значение None
```

Тип объявлен как `Dict`/`List`, но дефолтное значение — `None`. `__post_init__` это обходит, но:
- `mypy`/`pyright` будут сообщать об ошибках
- IDE показывает неверный контракт
- Нарушает принцип явного контракта

**Решение:**

```python
timeouts: Optional[Dict[str, float]] = None
capabilities: Optional[List[str]] = None
# или
timeouts: Dict[str, float] = field(default_factory=dict)
capabilities: List[str] = field(default_factory=list)
```

---

## УМЕРЕННЫЕ ПРОБЛЕМЫ

### 3. Несогласованный паттерн доступа к сервисам

**Файлы:** все модули в `modules/`

В одних модулях используется:
```python
self.context.services  # безопасный паттерн
```

В других:
```python
self.runtime.kernel_context.get_service("service_registry")  # хрупкий паттерн
```

Второй паттерн работает только если `self.runtime is not None` (см. Проблему #1).

**Решение:** Стандартизировать все модули на `self.context.services`.

---

### 4. Мутабельные дефолты в dataclass (anti-pattern)

**Файл:** `core/capability/protocol.py`

```python
@dataclass
class ProviderMetadata:
    timeouts: Dict[str, float] = None

    def __post_init__(self):
        if self.timeouts is None:
            self.timeouts = {}
```

Хотя `__post_init__` нейтрализует риск шаринга мутабельного объекта, паттерн создаёт путаницу. Лучше использовать `field(default_factory=dict)`.

---

## ЧТО РАБОТАЕТ КОРРЕКТНО

Рефакторинг структуры файлов прошёл успешно — все пути импортов обновлены:

| Удалённый файл | Новый путь |
|---|---|
| `core/auth_contextvars.py` | `core/runtime/auth_contextvars.py` |
| `core/exceptions/__init__.py` + `errors.py` | `core/exceptions.py` |
| `core/health_monitor.py` | `core/observability/health_monitor.py` |
| `core/logger_helper.py` | `core/observability/logger_helper.py` |
| `core/integration_registry.py` | `core/kernel/integration_registry.py` |
| `core/messaging/inmemory.py` + `models.py` | `core/messaging.py` |
| `core/module/__init__.py` + `manager.py` + `models.py` | `core/module.py` |
| `core/operation_context.py` | `core/runtime/operation_context.py` |
| `core/remote_executor_interface.py` | `core/operations/remote_executor_interface.py` |
| `core/remote_provider.py` | `core/operations/remote_provider.py` |
| `core/state_engine.py` | `core/runtime/state_engine.py` |
| `core/storage_errors.py` | `core/adapters/storage_errors.py` |
| `core/system_context.py` | `core/runtime/system_context.py` |
| `core/capability_protocol.py` | `core/capability/protocol.py` |

- Синтаксических ошибок нет
- Циклических импортов нет (используется lazy loading в `__init__.py`)
- Консолидация файлов (`messaging.py`, `module.py`, `exceptions.py`) прошла корректно
