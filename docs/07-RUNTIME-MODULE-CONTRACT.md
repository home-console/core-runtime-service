# Контракт RuntimeModule и ModuleManager

> **Статус:** Stable (v0.2.0)  
> **Версия контракта:** 1.0  
> **Breaking changes:** Любые изменения контракта считаются breaking

---

## Определение

**RuntimeModule** — обязательное расширение ядра Core Runtime, которое:
- Регистрируется напрямую в `CoreRuntime` через `ModuleManager`
- **НЕ зависит** от `PluginManager` или `BasePlugin`
- Использует **только Core API** (storage, event_bus, service_registry, state_engine, http)
- Работает даже если `PluginManager` отключён
- Предоставляет критическую доменную функциональность
- **Считается доверенным кодом** (в отличие от Plugin)

**RuntimeModule ≠ Plugin:**
- Module = обязательный домен (всегда доступен, статическая регистрация, **доверенный код**)
- Plugin = опциональное расширение (можно включать/выключать, manifest-based, **недоверенный код**)

---

## Обязательный контракт RuntimeModule

### Базовый класс

```python
from core.runtime_module import RuntimeModule

class MyModule(RuntimeModule):
    @property
    def name(self) -> str:
        """Уникальное имя модуля (обязательно, abstract)."""
        return "my_module"
    
    async def register(self) -> None:
        """Регистрация сервисов, подписок, HTTP endpoints (опционально)."""
        pass
    
    async def start(self) -> None:
        """Инициализация при старте runtime (опционально)."""
        pass
    
    async def stop(self) -> None:
        """Cleanup при остановке runtime (опционально)."""
        pass
```

### Обязательные методы

| Метод | Тип | Обязательность | Назначение |
|-------|-----|----------------|------------|
| `name` | `@property` | **Обязательно** (abstract) | Уникальное имя модуля |
| `register()` | `async` | Опционально (no-op по умолчанию) | Регистрация в CoreRuntime |
| `start()` | `async` | Опционально (no-op по умолчанию) | Инициализация при старте |
| `stop()` | `async` | Опционально (no-op по умолчанию) | Cleanup при остановке |

---

## Гарантии жизненного цикла

### Порядок вызовов

```
__init__(runtime) → register() → start() → stop()
```

**Строгие гарантии:**
1. `__init__(runtime)` вызывается при создании экземпляра модуля
2. `register()` вызывается **ровно один раз** при `ModuleManager.register(module)`
3. `start()` вызывается **ровно один раз** при `ModuleManager.start_all()`
4. `stop()` вызывается **ровно один раз** при `ModuleManager.stop_all()`
5. `stop()` вызывается **даже при частичном старте** (если `start()` упал)

### Идемпотентность

**Требования к `register()`:**
- `register()` **должен быть идемпотентным** (повторные вызовы безопасны)
- Модуль должен проверять, зарегистрированы ли сервисы/подписки перед повторной регистрацией
- `ModuleManager` защищает от двойной регистрации одного имени, но модуль должен быть готов к повторным вызовам

**Пример идемпотентной регистрации:**
```python
async def register(self):
    # Проверяем, не зарегистрирован ли сервис
    if not await self.runtime.service_registry.has_service("my.service"):
        await self.runtime.service_registry.register("my.service", handler)
```

### REQUIRED vs OPTIONAL

**REQUIRED модули:**
- Обязательны для работы runtime
- Runtime **НЕ стартует**, если REQUIRED модуль:
  - не зарегистрировался (не найден, не импортирован)
  - не смог выполниться `register()` (исключение)
  - упал в `start()` (исключение)
- Ошибки в REQUIRED модулях приводят к `RuntimeError` и остановке runtime

**OPTIONAL модули:**
- Могут отсутствовать или фейлиться без остановки runtime
- Ошибки в OPTIONAL модулях логируются, но не останавливают runtime

---

## Обработка ошибок

### Что модуль МОЖЕТ бросать

**В `register()`:**
- Любые исключения (`Exception`, `ValueError`, `RuntimeError`, и т.д.)
- Для REQUIRED модулей: исключение останавливает регистрацию и runtime не стартует
- Для OPTIONAL модулей: исключение логируется, модуль пропускается

**В `start()`:**
- Любые исключения
- Для REQUIRED модулей: исключение останавливает `start_all()` и runtime не стартует
- Для OPTIONAL модулей: исключение логируется, runtime продолжает работу

**В `stop()`:**
- Любые исключения (но рекомендуется избегать)
- Исключения логируются, но **не останавливают** остановку других модулей
- `stop()` должен быть безопасным (можно вызывать даже если `start()` не был вызван)

### Что модуль НЕ должен бросать

**В `__init__()`:**
- Исключения в `__init__()` должны быть минимальными (только критичные ошибки)
- `__init__()` не должен выполнять тяжёлые операции или обращаться к runtime API

**Рекомендации:**
- Используйте try/except для обработки ошибок внутри методов
- Логируйте ошибки через `service_registry.call("logger.log", ...)`
- Не проглатывайте критические ошибки без логирования

---

## Что RuntimeModule МОЖЕТ делать

✅ **Использовать Core API:**
- `runtime.storage` — персистентное key-value хранилище
- `runtime.state_engine` — read-only кеш состояния
- `runtime.event_bus` — pub/sub шина событий
- `runtime.service_registry` — реестр сервисов (RPC)
- `runtime.http` — реестр HTTP endpoints

✅ **Регистрировать сервисы:**
```python
async def register(self):
    await self.runtime.service_registry.register("my.service", handler)
```

✅ **Подписываться на события:**
```python
async def register(self):
    await self.runtime.event_bus.subscribe("event.type", handler)

async def stop(self):
    await self.runtime.event_bus.unsubscribe("event.type", handler)
```

✅ **Регистрировать HTTP endpoints:**
```python
async def register(self):
    from core.http_registry import HttpEndpoint
    self.runtime.http.register(HttpEndpoint("GET", "/api/path", "my.service"))
```

✅ **Использовать Storage для персистентности:**
```python
await self.runtime.storage.set("namespace", "key", value)
data = await self.runtime.storage.get("namespace", "key")
```

✅ **Читать StateEngine (read-only):**
```python
state = await self.runtime.state_engine.get("key")
keys = await self.runtime.state_engine.keys()
```

✅ **Вызывать другие сервисы:**
```python
result = await self.runtime.service_registry.call("other.service", arg1, arg2)
```

✅ **Хранить временные кеши в памяти:**
```python
self._cache = {}  # Временный кеш - допустимо
```

---

## Что RuntimeModule НЕ МОЖЕТ делать

❌ **Зависеть от PluginManager:**
```python
# ЗАПРЕЩЕНО
self.runtime.plugin_manager.load_plugin(...)
self.runtime.plugin_manager.list_plugins()
```

❌ **Использовать manifests или marketplace:**
```python
# ЗАПРЕЩЕНО
manifest = load_manifest(...)
```

❌ **Динамически загружаться/выгружаться:**
```python
# ЗАПРЕЩЕНО - модули регистрируются статически при создании CoreRuntime
# Нет методов для hot-reload или динамической загрузки
```

❌ **Импортировать другие модули напрямую:**
```python
# ЗАПРЕЩЕНО
from modules.other_module import OtherModule
from modules.other_module.services import some_function

# РАЗРЕШЕНО - через ServiceRegistry
result = await self.runtime.service_registry.call("other.service")
```

❌ **Хранить персистентное состояние в памяти:**
```python
# ЗАПРЕЩЕНО
self._persistent_state = {}  # Должно быть в Storage

# РАЗРЕШЕНО
await self.runtime.storage.set("namespace", "key", value)
```

❌ **Зависеть от порядка регистрации других модулей:**
```python
# ЗАПРЕЩЕНО - модули не должны знать о других модулях
# Используйте ServiceRegistry для проверки доступности сервисов
if await self.runtime.service_registry.has_service("other.service"):
    result = await self.runtime.service_registry.call("other.service")
```

❌ **Блокировать event loop в lifecycle методах:**
```python
# ЗАПРЕЩЕНО
async def start(self):
    time.sleep(10)  # Блокирующий вызов

# РАЗРЕШЕНО
async def start(self):
    await asyncio.sleep(10)  # Неблокирующий вызов
```

❌ **Модифицировать Core Runtime напрямую:**
```python
# ЗАПРЕЩЕНО - прямой доступ к внутренностям Core
self.runtime.event_bus._handlers = {}  # Прямой доступ к приватным атрибутам
```

---

## Безопасность и доверие

### RuntimeModule как доверенный код

**Статус:** Stable (архитектурное требование)

- RuntimeModule считается **доверенным кодом** (в отличие от Plugin)
- Модули регистрируются статически при создании CoreRuntime
- Модули не загружаются из внешних источников
- Модули имеют полный доступ к Core API без ограничений
- Ошибки в REQUIRED модулях останавливают runtime (критическая функциональность)

**Отличие от Plugin:**
- Plugin = недоверенный код (загружается через manifest, может быть из marketplace)
- RuntimeModule = доверенный код (статическая регистрация, часть ядра)

**Рекомендации:**
- Модули должны быть тщательно протестированы
- Модули не должны содержать уязвимостей
- Изменения в модулях требуют тщательного ревью

---

## Контракт ModuleManager

### Обязательные гарантии

**Регистрация:**
- `register(module)` защищает от двойной регистрации одного имени
- Один экземпляр модуля может быть зарегистрирован только один раз
- Повторная регистрация того же экземпляра игнорируется (идемпотентность)
- Двойная регистрация разных экземпляров с одним именем → `ValueError`

**Порядок регистрации BUILTIN_MODULES:**
- Модули регистрируются в порядке, указанном в `BUILTIN_MODULES`
- **ВАЖНО:** `logger` должен быть первым, так как он нужен для логирования других модулей
- Порядок регистрации: `logger` → `api` → `admin` → `devices` → `automation` → `presence`
- Порядок запуска (`start_all()`): модули запускаются в порядке регистрации

**Запуск:**
- `start_all()` вызывает `start()` для всех зарегистрированных модулей **в порядке регистрации**
- Для REQUIRED модулей: ошибка в `start()` → `RuntimeError`, runtime не стартует
- Для OPTIONAL модулей: ошибка логируется, runtime продолжает работу
- Если REQUIRED модуль упал → остальные модули не запускаются, `stop_all()` вызывается для cleanup

**Остановка:**
- `stop_all()` вызывает `stop()` для всех зарегистрированных модулей
- Ошибки в `stop()` логируются, но не останавливают остановку других модулей
- `stop_all()` вызывается даже при частичном старте (если `start()` упал)

**Обработка ошибок REQUIRED vs OPTIONAL:**
- **REQUIRED модули:**
  - Ошибка в `register()` → `RuntimeError`, runtime не стартует
  - Ошибка в `start()` → `RuntimeError`, runtime не стартует
  - Ошибка в `stop()` → логируется, но не останавливает остановку других модулей
- **OPTIONAL модули:**
  - Ошибка в `register()` → логируется, модуль пропускается
  - Ошибка в `start()` → логируется, runtime продолжает работу
  - Ошибка в `stop()` → логируется, но не останавливает остановку других модулей

**Обнаружение:**
- `_discover_module()` изолирован для будущего RemoteModuleManager
- `_create_module_instance()` изолирован для будущего RemoteModuleManager

---

## Стабильность контракта

**Контракт версии 1.0 является стабильным:**
- Методы `register()`, `start()`, `stop()` остаются async
- Сигнатура методов не изменится
- Добавление новых обязательных методов = breaking change
- Изменение порядка вызовов = breaking change

**Future: Remote RuntimeModule:**
- Контракт остаётся стабильным при переходе на proxy-based execution
- Методы остаются async, взаимодействие через ServiceRegistry/EventBus
- Модули не должны знать, выполняются ли они локально или удалённо

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

### Модуль с идемпотентной регистрацией
```python
class ServiceModule(RuntimeModule):
    @property
    def name(self) -> str:
        return "service"
    
    async def register(self):
        # Идемпотентная регистрация
        if not await self.runtime.service_registry.has_service("service.action"):
            await self.runtime.service_registry.register("service.action", self._handler)
    
    async def _handler(self, arg):
        return {"result": arg}
```

### Модуль с обработкой ошибок
```python
class RobustModule(RuntimeModule):
    @property
    def name(self) -> str:
        return "robust"
    
    async def register(self):
        try:
            await self.runtime.service_registry.register("robust.action", self._handler)
        except ValueError:
            # Сервис уже зарегистрирован - это нормально (идемпотентность)
            pass
        except Exception as e:
            # Логируем критические ошибки
            try:
                await self.runtime.service_registry.call(
                    "logger.log",
                    level="error",
                    message=f"Failed to register robust module: {e}",
                    module="robust"
                )
            except Exception:
                pass
            # Пробрасываем исключение для REQUIRED модулей
            raise
    
    async def stop(self):
        # stop() должен быть безопасным
        try:
            await self.runtime.service_registry.unregister("robust.action")
        except Exception:
            # Игнорируем ошибки при остановке
            pass
```

---

## См. также

- [04-CORE-RUNTIME-CONTRACT.md](04-CORE-RUNTIME-CONTRACT.md) — контракты Core Runtime
- [06-MODULES-ARCHITECTURE.md](06-MODULES-ARCHITECTURE.md) — архитектура модулей
- [02-MODULES-AND-PLUGINS.md](02-MODULES-AND-PLUGINS.md) — разделение модулей и плагинов
