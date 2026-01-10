# Архитектура Modules (Встроенные домены)

## Принципы разделения

### Core (Инфраструктура)
**Что:** Низкоуровневые компоненты, не знающие о доменах.

**Компоненты:**
- `EventBus` — шина событий
- `ServiceRegistry` — реестр сервисов
- `Storage` — источник истины (persistence)
- `StateEngine` — read-only кэш состояния
- `PluginManager` — менеджер опциональных плагинов

**Правила:**
- Core НЕ знает о доменах (devices, automation, presence)
- Core предоставляет только API (storage, event_bus, service_registry)
- Core не содержит бизнес-логики

---

### Modules (Обязательные домены)
**Что:** Встроенные домены системы, которые всегда доступны.

**Примеры:**
- `devices` — управление устройствами
- `automation` — автоматизация
- `presence` — отслеживание присутствия

**Правила:**
- Регистрируются **напрямую** в CoreRuntime (не через PluginManager)
- Используют **только** Core API (storage, event_bus, service_registry)
- **Обязательны** для работы системы
- **Не зависят** от PluginManager
- Идемпотентная регистрация

**Структура:**
```
modules/<domain>/
├── __init__.py      # экспортирует <Domain>Module
├── module.py        # <Domain>Module(RuntimeModule)
├── services.py      # доменные сервисы
└── handlers.py      # обработчики событий
```

**Контракт:**
```python
from core.runtime_module import RuntimeModule

class DomainModule(RuntimeModule):
    @property
    def name(self) -> str:
        return "domain"
    
    def register(self) -> None:
        # Регистрация сервисов
        self.runtime.service_registry.register("domain.action", handler)
        
        # Подписка на события
        self.runtime.event_bus.subscribe("event.type", handler)
    
    async def start(self) -> None:
        # Инициализация при старте
        pass
    
    async def stop(self) -> None:
        # Отписка и cleanup
        self.runtime.event_bus.unsubscribe("event.type", handler)
        self.runtime.service_registry.unregister("domain.action")
```

---

### Plugins (Опциональные адаптеры)
**Что:** Внешние интеграции и адаптеры, которые можно включать/выключать.

**Примеры:**
- `yandex_smart_home_real` — интеграция с Яндекс.Умный дом
- `oauth_yandex` — OAuth авторизация
- `api_gateway_plugin` — HTTP API gateway
- `admin_plugin` — административный интерфейс
- `remote_plugin_proxy` — удалённые плагины

**Правила:**
- Регистрируются через **PluginManager**
- Наследуются от **BasePlugin**
- **Опциональны** — система работает без них
- Могут использовать Modules через ServiceRegistry/EventBus
- Могут предоставлять HTTP endpoints через HttpRegistry

**Структура:**
```python
class SomePlugin(BasePlugin):
    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(name="...", version="...")
    
    async def on_load(self):
        # Регистрация сервисов, HTTP endpoints
        pass
    
    async def on_start(self):
        # Подписка на события, инициализация
        pass
    
    async def on_stop(self):
        # Отписка, cleanup
        pass
```

---

## Критерии разделения

### Когда код должен быть Module?

✅ **ДА, если:**
- Это **обязательный домен** системы (devices, automation, presence)
- Домен должен работать **без PluginManager**
- Домен использует **только Core API** (storage, event_bus, service_registry)
- Домен **не зависит** от внешних интеграций
- Домен предоставляет **базовую функциональность** системы

❌ **НЕТ, если:**
- Это интеграция с внешним сервисом (Yandex, OAuth)
- Это опциональная функциональность (admin UI, API gateway)
- Это адаптер для внешнего протокола
- Это зависит от внешних библиотек/API

### Когда код должен быть Plugin?

✅ **ДА, если:**
- Это **интеграция** с внешним сервисом
- Это **опциональная** функциональность
- Это **адаптер** для внешнего протокола/API
- Это зависит от внешних библиотек
- Это можно **включать/выключать** без потери базовой функциональности

❌ **НЕТ, если:**
- Это обязательный домен системы
- Это базовая функциональность (devices, automation)
- Это должно работать без PluginManager

### Когда код должен быть в Core?

✅ **ДА, если:**
- Это **инфраструктурный** компонент
- Это **не знает** о доменах
- Это предоставляет **низкоуровневый API**
- Это используется **всеми** модулями/плагинами

❌ **НЕТ, если:**
- Это содержит бизнес-логику
- Это знает о конкретных доменах
- Это можно реализовать как Module

---

## Регистрация модулей

### Автоматическая регистрация

Модули регистрируются автоматически при создании CoreRuntime:

```python
# core/runtime.py
class CoreRuntime:
    def __init__(self, storage_adapter):
        # ... инициализация компонентов
        self.module_manager = ModuleManager()
        
        # Регистрация встроенных модулей
        self.module_manager.register_builtin_modules(self)
```

### Список модулей

Список обязательных модулей определён в `core/module_manager.py`:

```python
BUILTIN_MODULES = [
    "devices",     # DevicesModule
    "automation",  # AutomationModule
    "presence",    # PresenceModule
]
```

### Идемпотентность

Регистрация модулей идемпотентна — `ModuleManager.register()` можно вызывать многократно без побочных эффектов.

---

## Миграция из Plugins в Modules

### Текущее состояние

- ✅ `devices` — мигрирован в DevicesModule
- ✅ `automation` — мигрирован в AutomationModule
- ✅ `presence` — мигрирован в PresenceModule

Все домены теперь реализованы как RuntimeModule и регистрируются автоматически через ModuleManager.

---

## Эталонная структура проекта

```
core-runtime-service/
├── core/                    # Инфраструктура (Core)
│   ├── __init__.py
│   ├── runtime.py           # CoreRuntime
│   ├── module_manager.py    # ModuleManager (регистрация модулей)
│   ├── runtime_module.py    # RuntimeModule (базовый класс)
│   ├── event_bus.py
│   ├── service_registry.py
│   ├── storage.py
│   ├── state_engine.py
│   ├── plugin_manager.py
│   └── http_registry.py
│
├── modules/                 # Обязательные домены (Modules)
│   ├── devices/
│   │   ├── __init__.py      # экспортирует DevicesModule
│   │   ├── module.py        # DevicesModule(RuntimeModule)
│   │   ├── services.py
│   │   └── handlers.py
│   ├── automation/
│   │   ├── __init__.py      # экспортирует AutomationModule
│   │   ├── module.py        # AutomationModule(RuntimeModule)
│   │   └── handlers.py
│   └── presence/
│       ├── __init__.py      # экспортирует PresenceModule
│       └── module.py        # PresenceModule(RuntimeModule)
│
├── plugins/                 # Опциональные адаптеры (Plugins)
│   ├── base_plugin.py
│   ├── yandex_smart_home_real.py
│   ├── oauth_yandex.py
│   ├── api_gateway_plugin.py
│   ├── admin_plugin.py
│   ├── presence_plugin.py  # DEPRECATED (shim)
│   └── automation_plugin.py # DEPRECATED (shim)
│
└── adapters/                # Адаптеры storage
    └── sqlite_adapter.py
```

---

## Чеклист для решений

### Это Module?
- [ ] Обязательный домен системы?
- [ ] Должен работать без PluginManager?
- [ ] Использует только Core API?
- [ ] Не зависит от внешних интеграций?
- [ ] Базовая функциональность?

**Если все ✅ → Module**

### Это Plugin?
- [ ] Интеграция с внешним сервисом?
- [ ] Опциональная функциональность?
- [ ] Адаптер для внешнего протокола?
- [ ] Можно включать/выключать?

**Если все ✅ → Plugin**

### Это Core?
- [ ] Инфраструктурный компонент?
- [ ] Не знает о доменах?
- [ ] Низкоуровневый API?
- [ ] Используется всеми модулями?

**Если все ✅ → Core**

---

## Архитектурные гарантии

1. **Модули обязательны** — система не работает без них
2. **Плагины опциональны** — система работает без них
3. **Core не знает доменов** — только предоставляет API
4. **Модули не зависят от PluginManager** — работают напрямую с Core
5. **Плагины могут использовать модули** — через ServiceRegistry/EventBus

---

## Следующие шаги

1. ✅ Создать формальный контракт (RuntimeModule, ModuleManager)
2. ✅ Централизовать регистрацию в CoreRuntime
3. ✅ Мигрировать все домены (devices, automation, presence) в RuntimeModule
4. ✅ Пометить старые плагины как DEPRECATED
5. ✅ Обновить документацию
6. ⏳ Добавить тесты для ModuleManager
7. ⏳ Улучшить обработку ошибок
