# Modules и Plugins — разделение ответственности

> **Статус:** Stable (введено в v0.2.0)  
> **Последнее изменение:** 2026-01-09

---

## Проблема, которую решает это разделение

До v0.2.0 вся логика реализовывалась как plugins. Это создавало проблему:
- **Доменная логика** (devices, automation) становилась опциональной
- **Runtime зависел от PluginManager** для базовой функциональности
- **Тесты требовали загрузки плагинов** даже для проверки Core API

Решение: разделить на **обязательные modules** и **опциональные plugins**.

---

## Определения

### Module (модуль)
**Обязательная** доменная логика, которая:
- Регистрируется в `CoreRuntime` при инициализации
- НЕ зависит от `BasePlugin` или `PluginManager`
- Работает даже если `PluginManager` отключён
- Предоставляет критическую функциональность (devices, presence)

**Расположение:** `modules/`

**Пример:** `modules/devices/` — доменная логика управления устройствами

### Plugin (плагин)
**Опциональное** расширение, которое:
- Наследуется от `BasePlugin`
- Загружается через `PluginManager.load_plugin()`
- Может быть включён/выключён без перезапуска
- Предоставляет интеграции, UI, оркестрацию

**Расположение:** `plugins/`

**Пример:** `plugins/yandex_smart_home_real.py` — интеграция с Яндекс API

---

## Критерии выбора: module или plugin?

### Используйте MODULE если:
- ✅ Это **доменная логика** (devices, automation rules, presence)
- ✅ Функциональность **критична** для работы системы
- ✅ Код **стабильный** и редко меняется
- ✅ Требуется **детерминированная доступность** (всегда присутствует)
- ✅ Другие компоненты **жёстко зависят** от этой логики

### Используйте PLUGIN если:
- ✅ Это **интеграция** с внешним API (Yandex, Alexa, OAuth)
- ✅ Это **UI/адаптер** (api_gateway, admin panel)
- ✅ Функциональность **опциональная** (можно отключить)
- ✅ Код **экспериментальный** или часто меняется
- ✅ Требуется **hot reload** (включить/выключить без перезапуска)

---

## Примеры из текущей кодовой базы

| Компонент | Тип | Причина |
|-----------|-----|---------|
| `modules/devices/` | Module | Доменная логика, критична для system |
| `plugins/yandex_smart_home_real.py` | Plugin | Интеграция, опциональна |
| `plugins/api_gateway_plugin.py` | Plugin | HTTP адаптер, опциональный |
| `plugins/oauth_yandex.py` | Plugin | Интеграция OAuth, опциональна |
| `plugins/system_logger_plugin.py` | Plugin | Инфраструктура, но опциональна |
| `plugins/automation_stub_plugin.py` | Plugin | Демонстрация, не критична |

**Будущее:** `modules/automation/` — когда automation станет stable, переместим в modules.

---

## Архитектура module

### Структура файлов

```python
modules/devices/
├── __init__.py         # точка входа: register_devices(runtime)
├── services.py         # бизнес-логика сервисов
└── handlers.py         # event handlers
```

### Регистрация в Runtime

**`modules/devices/__init__.py`:**
```python
def register_devices(runtime) -> dict:
    """
    Регистрирует devices domain в CoreRuntime.
    
    Возвращает dict с `unregister()` для cleanup.
    """
    # Регистрация сервисов
    runtime.service_registry.register("devices.create", ...)
    runtime.service_registry.register("devices.get", ...)
    
    # Подписка на события
    runtime.event_bus.subscribe("external.device_discovered", ...)
    
    # Возвращаем cleanup функцию
    def unregister():
        runtime.service_registry.unregister("devices.create")
        # ...
    
    return {"unregister": unregister}
```

### Инициализация в CoreRuntime

**`core/runtime.py`:**
```python
class CoreRuntime:
    def __init__(self, storage_adapter):
        # ... инициализация компонентов
        
        # Регистрация built-in modules
        try:
            from modules.devices import register_devices
            res = register_devices(self)
            self._module_unregistrars["devices"] = res.get("unregister")
        except ImportError:
            # modules опциональны для обратной совместимости
            pass
```

**Ключевое отличие:** Module регистрируется в `__init__`, а не через PluginManager.

---

## Архитектура plugin (для сравнения)

### Структура

```python
plugins/yandex_smart_home_real.py  # единственный файл или пакет

class YandexSmartHomeRealPlugin(BasePlugin):
    def __init__(self, runtime):
        super().__init__(runtime)
    
    async def on_load(self):
        # регистрация сервисов
        pass
    
    async def on_start(self):
        # подписка на события
        pass
    
    async def on_stop(self):
        # отписка
        pass
    
    async def on_unload(self):
        # cleanup
        pass
```

### Загрузка через PluginManager

```python
plugin = YandexSmartHomeRealPlugin(runtime)
await runtime.plugin_manager.load_plugin(plugin)
await runtime.plugin_manager.start_plugin("yandex_smart_home_real")
```

**Ключевое отличие:** Plugin управляется PluginManager, имеет lifecycle hooks.

---

## Migration Guide: Plugin → Module

### Когда нужна миграция?
Если плагин стал **критически важным** и используется всегда → переведите в module.

### Шаги миграции

#### 1. Создать structure в modules/

```bash
mkdir -p modules/my_domain
touch modules/my_domain/__init__.py
touch modules/my_domain/services.py
touch modules/my_domain/handlers.py
```

#### 2. Перенести логику

**Было (plugin):**
```python
class MyPlugin(BasePlugin):
    async def on_load(self):
        self.runtime.service_registry.register("my.service", self.my_method)
    
    async def my_method(self, arg):
        # бизнес-логика
        return result
```

**Стало (module):**
```python
# modules/my_domain/services.py
async def my_method(runtime, arg):
    # бизнес-логика (runtime передаётся явно)
    return result

# modules/my_domain/__init__.py
def register_my_domain(runtime):
    from . import services
    
    async def _wrapper(*args, **kwargs):
        return await services.my_method(runtime, *args, **kwargs)
    
    runtime.service_registry.register("my.service", _wrapper)
    
    def unregister():
        runtime.service_registry.unregister("my.service")
    
    return {"unregister": unregister}
```

#### 3. Зарегистрировать в CoreRuntime

**`core/runtime.py`:**
```python
# В __init__
try:
    from modules.my_domain import register_my_domain
    res = register_my_domain(self)
    self._module_unregistrars["my_domain"] = res.get("unregister")
except ImportError:
    pass
```

#### 4. Создать backward-compatible shim plugin (опционально)

Если существующий код импортирует `plugins.my_plugin`, создайте shim:

```python
# plugins/my_plugin.py
from plugins.base_plugin import BasePlugin, PluginMetadata
from modules.my_domain import register_my_domain

class MyPlugin(BasePlugin):
    """DEPRECATED: тонкий адаптер для обратной совместимости.
    
    Используйте modules.my_domain.register_my_domain(runtime) напрямую.
    """
    
    def __init__(self, runtime):
        super().__init__(runtime)
        self._unregister = None
    
    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="my_domain",
            version="1.0.0",
            description="[DEPRECATED] Adapter for modules.my_domain",
        )
    
    async def on_load(self):
        res = register_my_domain(self.runtime)
        self._unregister = res.get("unregister")
    
    async def on_unload(self):
        if callable(self._unregister):
            self._unregister()
```

#### 5. Обновить тесты

**Было:**
```python
plugin = MyPlugin(runtime)
await runtime.plugin_manager.load_plugin(plugin)
```

**Стало:**
```python
from modules.my_domain import register_my_domain
register_my_domain(runtime)
```

#### 6. Обновить документацию

- Удалить плагин из `plugins/README.md`
- Добавить модуль в `modules/README.md`
- Обновить архитектурные диаграммы

---

## Backward Compatibility Strategy

### Проблема
Существующий код импортирует `from plugins.devices_plugin import DevicesPlugin`.

### Решение: Shim Pattern

**`plugins/devices_plugin/__init__.py`:**
```python
"""DEPRECATED shim для обратной совместимости.

Домен devices перенесён в modules/devices. Импорт DevicesPlugin
оставлен для совместимости, но вызывает DeprecationWarning.
"""

import warnings

def __getattr__(name):
    if name == "DevicesPlugin":
        warnings.warn(
            "plugins.devices_plugin.DevicesPlugin is deprecated. "
            "Use modules.devices.register_devices(runtime) instead.",
            DeprecationWarning,
            stacklevel=2
        )
        # Вернуть thin adapter если необходимо
        from .adapter import DevicesPluginAdapter
        return DevicesPluginAdapter
    raise AttributeError(name)
```

### Deprecation Timeline

1. **v0.2.0** — Module введён, shim создан, DeprecationWarning
2. **v0.3.0** — Shim остаётся, документация обновлена
3. **v0.4.0** — Shim удалён, ImportError с helpful message

---

## Idempotent Registration

**Проблема:** Module может быть зарегистрирован дважды:
1. В CoreRuntime.__init__
2. Через backward-compatible plugin shim

**Решение:** Idempotent registration в module

```python
def register_devices(runtime):
    service_names = [
        ("devices.create", services.create_device),
        # ...
    ]
    
    registered = []
    
    for name, func in service_names:
        # Пропустить уже зарегистрированные
        if runtime.service_registry.has_service(name):
            continue
        
        async def _wrapper(*args, _func=func, **kwargs):
            return await _func(runtime, *args, **kwargs)
        
        try:
            runtime.service_registry.register(name, _wrapper)
            registered.append(name)
        except ValueError:
            # Concurrent registration — skip
            continue
    
    def unregister():
        for name in registered:
            runtime.service_registry.unregister(name)
    
    return {"unregister": unregister}
```

**Гарантия:** Повторные вызовы `register_devices()` безопасны.

---

## Тестирование modules

### Unit-тесты

Тестируйте функции сервисов напрямую:

```python
import pytest
from modules.devices import services

@pytest.mark.asyncio
async def test_create_device(memory_runtime):
    device = await services.create_device(
        memory_runtime,
        device_id="lamp_1",
        name="Kitchen Lamp",
        device_type="light"
    )
    
    assert device["id"] == "lamp_1"
    assert device["name"] == "Kitchen Lamp"
```

### Integration-тесты

Регистрируйте module в test runtime:

```python
@pytest.mark.asyncio
async def test_devices_integration(memory_runtime):
    from modules.devices import register_devices
    
    register_devices(memory_runtime)
    
    # Вызов через service_registry
    result = await memory_runtime.service_registry.call(
        "devices.create",
        "lamp_1",
        name="Kitchen Lamp"
    )
    
    assert result["id"] == "lamp_1"
```

---

## FAQ

### Можно ли module зависеть от другого module?
**Да**, но осторожно. Module может вызывать сервисы другого module через `runtime.service_registry.call()`. Избегайте прямых импортов.

### Можно ли plugin зависеть от module?
**Да**, это нормально. Plugin может вызывать сервисы module через `runtime.service_registry`.

### Можно ли module зависеть от plugin?
**Нет**. Module не должен знать о существовании plugins. Если нужна такая зависимость — значит, plugin должен стать module.

### Что если module и plugin регистрируют одинаковые сервисы?
Первый регистрант побеждает. `ServiceRegistry.register()` выбрасывает `ValueError` при дубликате. Используйте idempotent registration pattern.

### Где хранить состояние module?
**Только в `runtime.storage`**. Module НЕ должен хранить состояние в памяти (кроме временных кешей). `StateEngine` обновляется автоматически Core.

---

## См. также

- [01-ARCHITECTURE.md](01-ARCHITECTURE.md) — архитектурные инварианты
- [06-CONTRACTS.md](06-CONTRACTS.md) — реестр сервисов и событий
- [05-DEVELOPER-GUIDE.md](05-DEVELOPER-GUIDE.md) — правила разработки
