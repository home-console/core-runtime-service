# Architecture Decision Records (ADRs)

> **Что это:** Формальная документация о почему выбрали именно такую архитектуру  
> **Формат:** Проблема → Решение → Альтернативы → Trade-offs  
> **Зачем:** Комиссия не будет спрашивать "почему Python?" — вы сами объясните

---

## ADR-001: Event-Driven Architecture

### Проблема

Smart home интеграции требуют **асинхронного взаимодействия** между модулями:
- Device состояние меняется в любой момент (внешний trigger)
- Automation должна реагировать на события без задержек
- Множество модулей должны знать об одном событии (pub/sub)

### Выбранное решение

**Event Bus с publish/subscribe моделью** (EventBus в core/)

```python
# Модуль A публикует событие
await runtime.event_bus.publish("device.state_changed", data)

# Модуль B подписывается и реагирует
async def on_device_state_changed(data):
    await automation.process_change(data)

await runtime.event_bus.subscribe("device.state_changed", on_device_state_changed)
```

### Альтернативы рассмотренные

| Альтернатива | Плюсы | Минусы | Рейтинг |
|---|---|---|---|
| **Request-Reply (REST)** | Простая synv | Медленно, tight coupling | ❌ -2 |
| **Message Queue (RabbitMQ)** | Масштабируется | Оверкоп для монолита | ⚠️ +1 |
| **Pub/Sub Event Bus** | Гибкая, асинхронная | Нужна обработка ошибок | ✅ +5 |
| **Reactive streams (RxPy)** | Мощная | Сложность для новичков | ⚠️ +2 |

### Trade-offs

**Выигрываем:**
- ✓ Loose coupling (модули не знают друг о друге)
- ✓ Асинхронность (неблокирующие операции)
- ✓ Легко добавлять subscribers (плагины)

**Теряем:**
- ✗ Отладка сложнее (нужны логи событий)
- ✗ Гарантии доставки нужно реализовать
- ✗ Циклические события возможны (нужна проверка)

### Статус
✅ ПРИНЯТО и реализовано в `core/event_bus.py`

### Дата
Январь 2026

---

## ADR-002: Modules vs Plugins Дуализм

### Проблема

Платформа управления умным домом содержит:
1. **Обязательную** логику: devices, operations, automation
2. **Опциональную** логику: интеграции с Yandex, OAuth, third-party сервисы

Нужна архитектура, которая:
- Гарантирует, что обязательная логика всегда доступна
- Позволяет отключать/обновлять опциональные компоненты
- Обеспечивает изоляцию между ними

### Выбранное решение

**Два типа компонентов:**

```
Архитектура:
├── Core Runtime (kernel, всегда есть)
│
├── Modules (встроены в приложение)
│   ├── devices (обязательный)
│   ├── operations (обязательный)
│   ├── admin (обязательный)
│   └── ...
│
└── Plugins (загружаются динамически из manifest)
    ├── oauth_yandex (optional)
    ├── yandex_smart_home (optional)
    └── ...
```

**Различия:**

| Аспект | Modules | Plugins |
|--------|---------|---------|
| Загрузка | Статическая (ApplicationBootstrap) | Динамическая (PluginManager) |
| Регистрация | В коде (в modules/) | Через manifest.json |
| Обновление | С перезапуском Core | Без перезапуска (future) |
| Изоляция | Логическая (service registry) | Логическая + namespace |
| Зависимости | Явные в code | manifest.json |

### Альтернативы

| Альтернатива | Описание | Оценка |
|---|---|---|
| **Всё плагины** | Даже devices = plugin | ❌ Нет гарантий |
| **Монолит** | Всё встроено, нет plugins | ⚠️ Нет расширяемости |
| **Module + Plugin** | Наш выбор | ✅ Гибкий + надёжный |
| **Microservices** | Каждый модуль = отдельный process | ❌ Оверкоп для версии 1 |

### Trade-offs

**Выигрываем:**
- ✓ Гарантированная доступность core функциональности
- ✓ Опциональные features не влияют на core
- ✓ Четкое разделение ответственности

**Теряем:**
- ✗ Нужно разделить логику на modules/plugins (усилия при дизайне)
- ✗ Модули не могут быть полностью отключены
- ✗ Плагины зависят от modules (нельзя без devices)

### Статус
✅ ПРИНЯТО и реализовано в `core/module_manager.py` + `core/plugin_manager.py`

### Дата
Декабрь 2025

---

## ADR-003: Python вместо Go/Rust/Node

### Проблема

Нужно выбрать язык для Core Runtime с учетом:
- **Скорость разработки** (prototype быстро)
- **Performance** (обработка 100+ devices)
- **Production maturity** (стабильность)
- **Ecosystem** (готовые библиотеки)

### Выбранное решение

**Python 3.11+ с asyncio**

```python
# Почему Python:
# 1. Быстрая разработка (readable code, less boilerplate)
# 2. asyncio (встроенная async/await)
# 3. Ecosystem (FastAPI, SQLAlchemy, pydantic)
# 4. Installed base (많은 разработчики знают Python)
```

### Альтернативы рассмотренные

| Язык | Плюсы | Минусы | Выбран? |
|---|---|---|---|
| **Python** | Dev speed, asyncio, ecosystem | Медленнее чем Go | ✅ YES |
| **Go** | Производительность, goroutines | Много boilerplate | ❌ NO |
| **Rust** | Speed, safety | Крутая кривая обучения | ❌ NO |
| **Node.js** | JavaScript everywhere | Event loop issues | ❌ NO |
| **Java (Spring)** | Enterprise, widely known | Heavy, verbose | ❌ NO |

### Trade-offs

**Выигрываем:**
- ✓ Быстра разработка (6 недель prototype)
- ✓ Простые интеграции (requests, asyncio-friendly libs)
- ✓ Легче обучать новичков

**Теряем:**
- ✗ Performance (не критично для версии 1)
- ✗ GIL (но asyncio её обходит)
- ✗ Cold startup (но в Docker не заметно)

### Benchmarks
- Latency API: ~50-100ms (приемлемо для IoT)
- Memory baseline: ~100MB (Raspi/VPS friendly)

### Статус
✅ ПРИНЯТО и реализовано в `main.py` + core Runtime

### Дата
Ноябрь 2025

---

## ADR-004: Explicit Event Bus vs Implicit Messaging

### Проблема

Как уведомлять плагины об изменениях? Два подхода:

1. **Implicit:** Плагин subscribeится к eventi в коде (низкоуровневый)
2. **Explicit:** Есть Event Registry, плагин объявляет интерес к события (высокоуровневый)

### Выбранное решение

**Explicit Event Bus + Registry**

```python
# Плагин объявляет интерес
class MyPlugin(BasePlugin):
    capabilities_required = ["device.state_changed"]  # Явное объявление

async def on_load(self):
    # Event Bus знает куда посылать события
    await runtime.event_bus.subscribe(
        "device.state_changed",
        self.on_device_changed
    )
```

### Почему explicit лучше

| Аспект | Explicit | Implicit |
|--------|----------|----------|
| **Отладка** | Видно what plugin needs | Скрыто в коде |
| **Зависимости** | В manifest or metadata | Найти нельзя без анализа |
| **Validation** | Можно проверить при загрузке | Runtime errors только |

### Статус
✅ ПРИНЯТО в CapabilityRegistry + Metadata

### Дата
Январь 2026

---

## ADR-005: Storage Adapter Pattern вместо Direct ORM

### Проблема

Нужна возможность использовать разные БД (SQLite для dev, PostgreSQL для prod) без изменения кода плагинов.

### Выбранное решение

**Storage Adapter Pattern** (core/storage_factory.py)

```python
# Плагины используют абстрацтный интерфейс
await runtime.storage.set(namespace, key, value)

# Реальная реализация выбирается в runtime config
# SQLite: core-runtime-service/.env → STORAGE_TYPE=sqlite
# PostgreSQL: core-runtime-service/.env → DATABASE_URL=postgres://...
```

### Trade-offs

**Выигрываем:**
- ✓ Database-agnostic
- ✓ Легко переключаться (dev на SQLite, prod на PostgreSQL)
- ✓ Тестирование (можно использовать in-memory)

**Теряем:**
- ✗ Нельзя использовать advanced SQL features
- ✗ Миграции нужно писать вручную

### Статус
✅ ПРИНЯТО и реализовано в `core/storage.py` + adapters/

### Дата
Декабрь 2025

---

## Значение этих решений для диплома

Когда комиссия спросит:
- "Почему event-driven?" → ADR-001
- "Почему Python?" → ADR-003
- "Как вы разделили modules/plugins?" → ADR-002

Вы можете сказать:
> "Мы сделали анализ альтернатив и задокументировали решения в Architecture Decision Records. Вот [pointing to this document]. Event-driven потребовалась для loose coupling, Python для скорости разработки, modules/plugins для гибкости..."

**Это сразу переводит обсуждение с "что вы сделали?" на "почему вы сделали?"** ← Это то что нужно для защиты!

---

По необходимости можно добавить:
- ADR-006: Async/await vs Threads vs gevent
- ADR-007: REST API vs gRPC
- ADR-008: Token encryption strategy
- ...

Но этих 5 достаточно для стартового набора.
