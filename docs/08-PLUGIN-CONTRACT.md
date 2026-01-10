# Контракт Plugin и Manifest

> **Статус:** Stable (v0.2.0)  
> **Версия контракта:** 1.0  
> **Breaking changes:** Любые изменения контракта считаются breaking

---

## Определение

**Plugin** — опциональное расширение Core Runtime, которое:
- Наследуется от `BasePlugin`
- Загружается **ТОЛЬКО через manifest** (`plugin.json` или `manifest.json`)
- Считается **недоверенным кодом** (нет полной изоляции в текущей реализации)
- Может быть включён/выключён без перезапуска runtime
- Предоставляет интеграции, UI, оркестрацию

**Plugin ≠ RuntimeModule:**
- Plugin = опциональное расширение (manifest-based, динамическая загрузка)
- RuntimeModule = обязательный домен (статическая регистрация, всегда доступен)

---

## Контракт Manifest

### Обязательные поля

Manifest — JSON файл (`plugin.json` или `manifest.json`) со следующими полями:

```json
{
  "class_path": "plugins.my_plugin.plugin.MyPlugin",
  "name": "my_plugin",
  "version": "1.0.0",
  "description": "Описание плагина",
  "author": "Author Name",
  "dependencies": ["other_plugin"]
}
```

| Поле | Тип | Обязательность | Описание |
|------|-----|----------------|----------|
| `class_path` | `string` | **Обязательно** | Полный путь к классу плагина (module.path.ClassName) |
| `name` | `string` | **Обязательно** | Уникальное имя плагина (используется для зависимостей) |
| `version` | `string` | **Обязательно** | Версия плагина (semver рекомендуется) |
| `description` | `string` | Опционально | Описание функциональности плагина |
| `author` | `string` | Опционально | Автор плагина |
| `dependencies` | `array[string]` | Опционально | Список имён плагинов-зависимостей |

### Семантика dependencies

**Формат:**
- Массив строк с именами плагинов: `["plugin1", "plugin2"]`
- Пустой массив или отсутствие поля = нет зависимостей

**Гарантии:**
- Плагины загружаются в порядке топологической сортировки (алгоритм Кана)
- Зависимости должны быть загружены **до** загрузки плагина
- Если зависимость отсутствует → плагин **пропускается** (не загружается)
- Циклические зависимости обнаруживаются, но не блокируют загрузку других плагинов

**Пример:**
```json
{
  "name": "yandex_smart_home",
  "dependencies": ["oauth_yandex"]
}
```
→ `oauth_yandex` загрузится **перед** `yandex_smart_home`

### Правила Manifest

✅ **Разрешено:**
- Хранить manifest в `plugin.json` или `manifest.json`
- Указывать зависимости на другие плагины
- Использовать semver для версий

❌ **Запрещено:**
- Загружать плагин без manifest
- Указывать зависимости на RuntimeModule (модули всегда доступны)
- Использовать версионирование в dependencies (только имена плагинов)
- Циклические зависимости (обнаруживаются, но не гарантируют корректную работу)

---

## Контракт Plugin

### Базовый класс

```python
from core.base_plugin import BasePlugin, PluginMetadata

class MyPlugin(BasePlugin):
    @property
    def metadata(self) -> PluginMetadata:
        """Метаданные плагина (обязательно, abstract)."""
        return PluginMetadata(
            name="my_plugin",
            version="1.0.0",
            description="Описание",
            author="Author",
            dependencies=[]  # Зависимости из manifest переопределяют это
        )
    
    async def on_load(self) -> None:
        """Загрузка плагина (опционально)."""
        pass
    
    async def on_start(self) -> None:
        """Запуск плагина (опционально)."""
        pass
    
    async def on_stop(self) -> None:
        """Остановка плагина (опционально)."""
        pass
    
    async def on_unload(self) -> None:
        """Выгрузка плагина (опционально)."""
        pass
```

### Обязательные методы

| Метод | Тип | Обязательность | Назначение |
|-------|-----|----------------|------------|
| `metadata` | `@property` | **Обязательно** (abstract) | Метаданные плагина |
| `on_load()` | `async` | Опционально (no-op по умолчанию) | Загрузка плагина |
| `on_start()` | `async` | Опционально (no-op по умолчанию) | Запуск плагина |
| `on_stop()` | `async` | Опционально (no-op по умолчанию) | Остановка плагина |
| `on_unload()` | `async` | Опционально (no-op по умолчанию) | Выгрузка плагина |

### Гарантии жизненного цикла

**Порядок вызовов:**
```
__init__(runtime=None) → on_load() → on_start() → on_stop() → on_unload()
```

**Строгие гарантии:**
1. `__init__()` вызывается при создании экземпляра (runtime может быть None)
2. `PluginManager` устанавливает `runtime` перед вызовом `on_load()`
3. `on_load()` вызывается **ровно один раз** при `PluginManager.load_plugin()`
4. `on_start()` вызывается **ровно один раз** при `PluginManager.start_plugin()`
5. `on_stop()` вызывается **ровно один раз** при `PluginManager.stop_plugin()`
6. `on_unload()` вызывается **ровно один раз** при выгрузке плагина
7. `on_stop()` вызывается **перед** `on_unload()`

**Зависимости:**
- Все зависимости из `manifest.dependencies` загружены **до** вызова `on_load()`
- Плагин может вызывать сервисы зависимостей через `service_registry.call()`
- Если зависимость отсутствует → плагин **не загружается**

### Обработка ошибок

**В lifecycle методах:**
- Плагины могут бросать любые исключения
- Ошибки в `on_load()` → плагин не загружается, ошибка логируется
- Ошибки в `on_start()` → плагин не запускается, ошибка логируется
- Ошибки в `on_stop()` → ошибка логируется, остановка других плагинов продолжается
- Ошибки в `on_unload()` → ошибка логируется, выгрузка других плагинов продолжается

**Рекомендации:**
- Используйте try/except для обработки ошибок
- Логируйте ошибки через `service_registry.call("logger.log", ...)`
- Не проглатывайте критические ошибки без логирования

---

## Что Plugin МОЖЕТ делать

✅ **Использовать Core API:**
- `runtime.storage` — персистентное key-value хранилище
- `runtime.state_engine` — read-only кеш состояния
- `runtime.event_bus` — pub/sub шина событий
- `runtime.service_registry` — реестр сервисов (RPC)
- `runtime.http` — реестр HTTP endpoints

✅ **Регистрировать сервисы:**
```python
async def on_load(self):
    await self.runtime.service_registry.register("my.service", handler)
```

✅ **Подписываться на события:**
```python
async def on_load(self):
    await self.runtime.event_bus.subscribe("event.type", handler)

async def on_unload(self):
    await self.runtime.event_bus.unsubscribe("event.type", handler)
```

✅ **Регистрировать HTTP endpoints:**
```python
async def on_load(self):
    from core.http_registry import HttpEndpoint
    self.runtime.http.register(HttpEndpoint("GET", "/api/path", "my.service"))
```

✅ **Вызывать другие сервисы:**
```python
result = await self.runtime.service_registry.call("other.service", arg1, arg2)
```

✅ **Использовать переменные окружения:**
```python
url = self.get_env_config("API_URL", default="http://localhost")
enabled = self.get_env_config_bool("ENABLED", default=False)
port = self.get_env_config_int("PORT", default=8080)
```

✅ **Хранить временные кеши в памяти:**
```python
self._cache = {}  # Временный кеш - допустимо
```

---

## Что Plugin НЕ МОЖЕТ делать

❌ **Загружаться без manifest:**
```python
# ЗАПРЕЩЕНО - плагин загружается ТОЛЬКО через manifest
# Нет способа загрузить плагин без plugin.json или manifest.json
```

❌ **Импортировать другие плагины напрямую:**
```python
# ЗАПРЕЩЕНО
from plugins.other_plugin import OtherPlugin

# РАЗРЕШЕНО - через ServiceRegistry
result = await self.runtime.service_registry.call("other.service")
```

❌ **Импортировать RuntimeModule напрямую:**
```python
# ЗАПРЕЩЕНО
from modules.devices import DevicesModule

# РАЗРЕШЕНО - через ServiceRegistry
result = await self.runtime.service_registry.call("devices.list")
```

❌ **Хранить персистентное состояние в памяти:**
```python
# ЗАПРЕЩЕНО
self._persistent_state = {}  # Должно быть в Storage

# РАЗРЕШЕНО
await self.runtime.storage.set("namespace", "key", value)
```

❌ **Зависеть от порядка загрузки других плагинов:**
```python
# ЗАПРЕЩЕНО - плагины не должны знать о других плагинах
# Используйте ServiceRegistry для проверки доступности сервисов
if await self.runtime.service_registry.has_service("other.service"):
    result = await self.runtime.service_registry.call("other.service")
```

❌ **Блокировать event loop в lifecycle методах:**
```python
# ЗАПРЕЩЕНО
async def on_start(self):
    time.sleep(10)  # Блокирующий вызов

# РАЗРЕШЕНО
async def on_start(self):
    await asyncio.sleep(10)  # Неблокирующий вызов
```

❌ **Использовать PluginManager напрямую:**
```python
# ЗАПРЕЩЕНО
self.runtime.plugin_manager.load_plugin(...)
self.runtime.plugin_manager.list_plugins()
```

❌ **Модифицировать Core Runtime:**
```python
# ЗАПРЕЩЕНО
self.runtime.event_bus._handlers = {}  # Прямой доступ к внутренностям
```

---

## Безопасность и изоляция

### Текущие ограничения

**Статус:** Stable (текущее ограничение)

- Плагины работают в **одном процессе** → нет полной изоляции
- Плагины считаются **недоверенным кодом**
- Нет sandbox или ограничений на системные вызовы
- Плагины могут импортировать любые Python модули

**Рекомендации:**
- Для критичных плагинов используйте **Remote Plugins** (отдельный процесс)
- Валидируйте входные данные в сервисах плагинов
- Не загружайте плагины из недоверенных источников без проверки

### Валидация данных

**Статус:** Stable (текущее ограничение)

- Core Runtime **НЕ валидирует** данные плагинов
- Плагины сами отвечают за валидацию входных данных
- Плагины должны валидировать данные от других плагинов

### Marketplace

**Контракт достаточен для marketplace:**
- Manifest содержит всю необходимую информацию
- Зависимости разрешаются автоматически
- Версионирование через поле `version`
- Автор и описание для каталога

**Рекомендации для marketplace:**
- Валидировать manifest перед публикацией
- Проверять отсутствие циклических зависимостей
- Проверять корректность `class_path`
- Рекомендовать semver для версий

---

## Контракт PluginManager

### Manifest-based загрузка

**КРИТИЧЕСКИЕ ПРАВИЛА:**
- Плагины загружаются **ТОЛЬКО** если найден manifest (`plugin.json` или `manifest.json`)
- Без manifest плагин **НЕ загружается**
- **НЕ сканирует** Python файлы напрямую
- **НЕ импортирует** модули для поиска классов
- Загружает плагины в правильном порядке с учётом зависимостей

### Топологическая сортировка

**Алгоритм:** Kahn's algorithm

**Гарантии:**
- Плагины без зависимостей загружаются первыми
- Зависимости загружаются перед зависимыми плагинами
- Циклические зависимости обнаруживаются, но не блокируют загрузку других плагинов

**Пример:**
```
Плагины: A (deps: []), B (deps: [A]), C (deps: [A, B])
Порядок загрузки: A → B → C
```

### Обработка ошибок

**При загрузке:**
- Ошибки загрузки отдельных плагинов **игнорируются**
- Плагин с ошибкой **не загружается**, но другие плагины продолжают загружаться
- Ошибки логируются через logger

**При отсутствии зависимостей:**
- Плагин **пропускается** (не загружается)
- Ошибка логируется
- Другие плагины продолжают загружаться

---

## Примеры реализации

### Минимальный плагин
```python
class MinimalPlugin(BasePlugin):
    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="minimal",
            version="1.0.0",
            description="Минимальный плагин",
            author="Author"
        )
    # on_load(), on_start(), on_stop(), on_unload() - no-op по умолчанию
```

### Плагин с зависимостями
```python
class DependentPlugin(BasePlugin):
    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="dependent",
            version="1.0.0",
            description="Плагин с зависимостями",
            author="Author",
            dependencies=["oauth_yandex"]  # Зависимость из manifest переопределит это
        )
    
    async def on_load(self):
        # Зависимость уже загружена к этому моменту
        tokens = await self.runtime.service_registry.call("oauth_yandex.get_tokens")
```

### Плагин с обработкой ошибок
```python
class RobustPlugin(BasePlugin):
    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="robust",
            version="1.0.0",
            description="Плагин с обработкой ошибок",
            author="Author"
        )
    
    async def on_load(self):
        try:
            await self.runtime.service_registry.register("robust.action", self._handler)
        except ValueError:
            # Сервис уже зарегистрирован - это нормально
            pass
        except Exception as e:
            # Логируем критические ошибки
            try:
                await self.runtime.service_registry.call(
                    "logger.log",
                    level="error",
                    message=f"Failed to load robust plugin: {e}",
                    plugin="robust"
                )
            except Exception:
                pass
            raise
    
    async def on_unload(self):
        # on_unload() должен быть безопасным
        try:
            await self.runtime.service_registry.unregister("robust.action")
        except Exception:
            # Игнорируем ошибки при выгрузке
            pass
```

---

## Стабильность контракта

**Контракт версии 1.0 является стабильным:**
- Методы `on_load()`, `on_start()`, `on_stop()`, `on_unload()` остаются async
- Сигнатура методов не изменится
- Добавление новых обязательных методов = breaking change
- Изменение порядка вызовов = breaking change
- Manifest формат остаётся стабильным

**Future: Remote Plugins:**
- Контракт остаётся стабильным при переходе на remote execution
- Методы остаются async, взаимодействие через ServiceRegistry/EventBus
- Плагины не должны знать, выполняются ли они локально или удалённо

---

## См. также

- [04-CORE-RUNTIME-CONTRACT.md](04-CORE-RUNTIME-CONTRACT.md) — контракты Core Runtime
- [07-RUNTIME-MODULE-CONTRACT.md](07-RUNTIME-MODULE-CONTRACT.md) — контракт RuntimeModule
- [02-MODULES-AND-PLUGINS.md](02-MODULES-AND-PLUGINS.md) — разделение модулей и плагинов
- [05-REMOTE-PLUGIN-CONTRACT.md](05-REMOTE-PLUGIN-CONTRACT.md) — контракт для remote plugins
