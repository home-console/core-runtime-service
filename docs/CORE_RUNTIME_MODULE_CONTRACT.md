# Контракт RuntimeModule

> **Статус:** Stable (v0.2.0)  
> **Назначение:** Строгий контракт для обязательных доменных модулей системы

---

## Определение

**RuntimeModule** — обязательное расширение ядра Core Runtime, которое:
- Регистрируется напрямую в `CoreRuntime` через `ModuleManager`
- **НЕ зависит** от `PluginManager` или `BasePlugin`
- Использует **только Core API** (storage, event_bus, service_registry, state_engine, http)
- Работает даже если `PluginManager` отключён
- Предоставляет критическую доменную функциональность (devices, automation, presence, logger, api, admin)

**RuntimeModule ≠ Plugin:**
- Module = обязательный домен (всегда доступен)
- Plugin = опциональное расширение (можно включать/выключать)

---

## Обязательный контракт

### 1. Базовый класс

```python
from core.runtime_module import RuntimeModule

class MyModule(RuntimeModule):
    @property
    def name(self) -> str:
        """Уникальное имя модуля (обязательно)."""
        return "my_module"
    
    async def register(self) -> None:
        """Регистрация сервисов, подписок, HTTP endpoints."""
        pass
    
    async def start(self) -> None:
        """Инициализация при старте runtime."""
        pass
    
    async def stop(self) -> None:
        """Cleanup при остановке runtime."""
        pass
```

### 2. Обязательные методы

| Метод | Тип | Обязательность | Назначение |
|-------|-----|----------------|------------|
| `name` | `@property` | **Обязательно** | Уникальное имя модуля |
| `register()` | `async` | Опционально (no-op по умолчанию) | Регистрация в CoreRuntime |
| `start()` | `async` | Опционально (no-op по умолчанию) | Инициализация при старте |
| `stop()` | `async` | Опционально (no-op по умолчанию) | Cleanup при остановке |

---

## Гарантии жизненного цикла

### Порядок вызовов

```
__init__(runtime) → register() → start() → stop()
```

**Контракт:**
- `register()` вызывается **ровно один раз** при регистрации модуля через `ModuleManager.register()`
- `start()` вызывается **ровно один раз** при `runtime.start()`
- `stop()` вызывается **ровно один раз** при `runtime.stop()`
- `stop()` вызывается **даже при частичном старте** (если `start()` упал)

### Идемпотентность

- `register()` **должен быть идемпотентным** (повторные вызовы безопасны)
- `ModuleManager` защищает от двойной регистрации одного имени
- Один экземпляр модуля может быть зарегистрирован только один раз

### REQUIRED vs OPTIONAL

- **REQUIRED модули** обязательны для работы runtime
- Runtime **НЕ стартует**, если REQUIRED модуль:
  - не зарегистрировался
  - не смог выполниться `register()`
  - упал в `start()`
- **OPTIONAL модули** могут отсутствовать или фейлиться без остановки runtime

---

## Что модуль МОЖЕТ делать

✅ **Регистрировать сервисы:**
```python
async def register(self):
    self.runtime.service_registry.register("my.service", handler)
```

✅ **Подписываться на события:**
```python
async def register(self):
    await self.runtime.event_bus.subscribe("event.type", handler)
```

✅ **Регистрировать HTTP endpoints:**
```python
async def register(self):
    self.runtime.http.register(HttpEndpoint("GET", "/api/path", "my.service"))
```

✅ **Использовать Storage:**
```python
await self.runtime.storage.set("namespace", "key", value)
data = await self.runtime.storage.get("namespace", "key")
```

✅ **Читать StateEngine:**
```python
state = await self.runtime.state_engine.get("key")
keys = await self.runtime.state_engine.keys()
```

✅ **Вызывать другие сервисы:**
```python
result = await self.runtime.service_registry.call("other.service", arg1, arg2)
```

---

## Что модуль НЕ МОЖЕТ делать

❌ **Зависеть от PluginManager:**
```python
# ЗАПРЕЩЕНО
self.runtime.plugin_manager.load_plugin(...)
```

❌ **Использовать manifests или marketplace:**
```python
# ЗАПРЕЩЕНО
manifest = load_manifest(...)
```

❌ **Динамически загружаться/выгружаться:**
```python
# ЗАПРЕЩЕНО - модули регистрируются статически при создании CoreRuntime
```

❌ **Импортировать другие модули напрямую:**
```python
# ЗАПРЕЩЕНО
from modules.other_module import OtherModule

# РАЗРЕШЕНО - через ServiceRegistry
result = await self.runtime.service_registry.call("other.service")
```

❌ **Хранить состояние в памяти (кроме временных кешей):**
```python
# ЗАПРЕЩЕНО
self._state = {}  # Должно быть в Storage

# РАЗРЕШЕНО
await self.runtime.storage.set("namespace", "key", value)
```

---

## Core API (доступные примитивы)

Модуль имеет доступ только к следующим примитивам Core:

| Примитив | Назначение | Методы |
|----------|------------|--------|
| `runtime.storage` | Персистентное key-value хранилище | `set()`, `get()`, `delete()`, `list_keys()` |
| `runtime.state_engine` | Read-only кеш состояния | `get()`, `keys()` |
| `runtime.event_bus` | Pub/sub шина событий | `subscribe()`, `publish()`, `unsubscribe()` |
| `runtime.service_registry` | Реестр сервисов (RPC) | `register()`, `call()`, `has_service()`, `list_services()` |
| `runtime.http` | Реестр HTTP endpoints | `register()`, `list()` |

---

## Future: Remote RuntimeModule

**Планируется:** Вынос RuntimeModule в отдельный процесс через proxy-based execution.

**Контракт остаётся стабильным:**
- Методы `register()`, `start()`, `stop()` остаются async
- Взаимодействие через `ServiceRegistry` и `EventBus` (уже готово)
- `ModuleManager._discover_module()` и `_create_module_instance()` изолированы для будущего `RemoteModuleManager`
- Proxy будет прозрачно проксировать вызовы методов модуля через HTTP/gRPC

**Гарантии:**
- Контракт RuntimeModule не изменится при переходе на remote execution
- Модули не должны знать, выполняются ли они локально или удалённо
- Все взаимодействия идут через Core API (ServiceRegistry, EventBus)

---

## Примеры реализации

### Минимальный модуль
```python
class MinimalModule(RuntimeModule):
    @property
    def name(self) -> str:
        return "minimal"
    
    # register(), start(), stop() - no-op по умолчанию
```

### Модуль с сервисами
```python
class ServiceModule(RuntimeModule):
    @property
    def name(self) -> str:
        return "service"
    
    async def register(self):
        self.runtime.service_registry.register("service.action", self._handler)
    
    async def _handler(self, arg):
        return {"result": arg}
```

### Модуль с событиями
```python
class EventModule(RuntimeModule):
    @property
    def name(self) -> str:
        return "event"
    
    async def register(self):
        await self.runtime.event_bus.subscribe("event.type", self._handle)
    
    async def _handle(self, event_type, data):
        # обработка события
        pass
    
    async def stop(self):
        await self.runtime.event_bus.unsubscribe("event.type", self._handle)
```

---

## См. также

- [04-CORE-RUNTIME-CONTRACT.md](04-CORE-RUNTIME-CONTRACT.md) — контракты Core Runtime
- [06-MODULES-ARCHITECTURE.md](06-MODULES-ARCHITECTURE.md) — архитектура модулей
- [02-MODULES-AND-PLUGINS.md](02-MODULES-AND-PLUGINS.md) — разделение модулей и плагинов
