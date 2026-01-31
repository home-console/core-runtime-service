# Архитектурные варианты: Проблема с адаптерами и HTTP API

## Проблема

**Текущее состояние:**
- Есть `adapters/` с outbound адаптерами (storage)
- HTTP API — это тоже adapter (inbound), но сейчас размазан по модулям
- AdminModule разросся до **1309 строк** с endpoint'ами
- ApiModule — это gateway, но routes регистрируются внутри модулей
- Модули обрастают большой логикой, что не планировалось

**Вопрос:** Как правильно организовать архитектуру, чтобы разделить adapters и domain logic?

---

## Вариант 1: Чистый Hexagonal Architecture (Ports & Adapters)

### Структура
```
core-runtime-service/
├── core/                    # Domain Core (чистая бизнес-логика)
│   ├── operations.py
│   ├── runtime.py
│   ├── plugin_manager.py
│   └── ports/               # Интерфейсы (порты)
│       ├── storage_port.py
│       └── http_port.py
│
├── adapters/               # ВСЕ адаптеры (входящие + исходящие)
│   ├── inbound/           # Входящие (первичные) адаптеры
│   │   ├── http/
│   │   │   ├── __init__.py
│   │   │   ├── admin_routes.py        # Все admin endpoints
│   │   │   ├── operations_routes.py   # Все operations endpoints
│   │   │   ├── devices_routes.py      # Device endpoints
│   │   │   ├── api_gateway.py         # Gateway logic
│   │   │   └── dependencies.py        # FastAPI dependencies
│   │   ├── cli/           # Будущий CLI адаптер
│   │   └── websocket/     # Будущий WS адаптер
│   │
│   └── outbound/          # Исходящие (вторичные) адаптеры
│       ├── storage/
│       │   ├── __init__.py
│       │   ├── storage_port.py      # Интерфейс
│       │   ├── postgresql_adapter.py
│       │   └── sqlite_adapter.py
│       └── notifications/  # Будущие notification adapters
│
├── modules/               # Бизнес-логика (ТОНКИЕ!)
│   ├── admin/
│   │   ├── module.py      # Только регистрация в runtime
│   │   └── services.py    # Business services (если есть)
│   ├── operations/
│   │   ├── handlers.py    # Domain handlers
│   │   └── __init__.py
│   ├── devices/
│   │   ├── module.py
│   │   └── services.py    # Device domain logic
│   └── ...
```

### Как работает
1. **HTTP запрос** → `adapters/inbound/http/admin_routes.py`
2. **Routes** вызывают → `runtime.service_registry.call()` или `runtime.operations.create()`
3. **Core** выполняет бизнес-логику
4. **Core** использует → `adapters/outbound/storage/` через порты
5. **Модули** — только domain logic, без HTTP кода

### Плюсы ✅
- ✅ Классическая Hexagonal Architecture
- ✅ Чистое разделение: adapters vs domain
- ✅ Модули максимально тонкие
- ✅ Легко тестировать (mock адаптеров)
- ✅ Легко добавлять новые адаптеры (CLI, WS, gRPC)
- ✅ HTTP код в одном месте

### Минусы ❌
- ❌ Большой рефакторинг (перенос всех routes)
- ❌ Дублирование: routes + service definitions
- ❌ Нужно поддерживать синхронизацию между routes и services

### Оценка сложности
- **Рефакторинг:** 🔴 Высокая (4-6 часов)
- **Поддержка:** 🟢 Низкая (понятная структура)
- **Масштабируемость:** 🟢 Отличная

---

## Вариант 2: Модули с Inbound/Outbound разделением

### Структура
```
core-runtime-service/
├── core/                    # Core infrastructure
│   ├── operations.py
│   ├── runtime.py
│   └── ...
│
├── adapters/               # Только outbound адаптеры
│   ├── storage/
│   │   ├── storage_adapter.py
│   │   ├── postgresql_adapter.py
│   │   └── sqlite_adapter.py
│   └── external/          # Внешние интеграции
│       ├── yandex_client.py
│       └── oauth_client.py
│
├── modules/               # Модули = domain + inbound adapters
│   ├── admin/
│   │   ├── module.py           # Регистрация
│   │   ├── services.py         # Business logic
│   │   └── routes.py           # HTTP routes (inbound adapter)
│   ├── operations/
│   │   ├── handlers.py         # Domain handlers
│   │   └── routes.py           # HTTP routes
│   ├── devices/
│   │   ├── module.py
│   │   ├── services.py
│   │   └── routes.py
│   └── api/
│       └── module.py           # ApiModule как gateway
```

### Как работает
1. **Модуль** регистрируется в runtime
2. **module.py** импортирует `routes.py` и регистрирует в `runtime.http`
3. **ApiModule** читает `runtime.http` и создаёт FastAPI endpoints
4. **routes.py** вызывает `services.py` (domain logic)
5. **services.py** использует `adapters/` для persistence

### Плюсы ✅
- ✅ Минимальный рефакторинг (только split файлов)
- ✅ Модули остаются cohesive (domain + его HTTP interface)
- ✅ Понятная структура для разработчиков
- ✅ Легко найти код (всё в одном модуле)

### Минусы ❌
- ❌ Модули всё равно содержат adapter код (routes)
- ❌ Не чистая Hexagonal Architecture
- ❌ Сложнее переключаться между HTTP/CLI/WS

### Оценка сложности
- **Рефакторинг:** 🟡 Средняя (2-3 часа)
- **Поддержка:** 🟡 Средняя (нужно понимать разницу)
- **Масштабируемость:** 🟡 Хорошая

---

## Вариант 3: Hybrid (Pragmatic) подход

### Структура
```
core-runtime-service/
├── core/                    # Core infrastructure
│   ├── operations.py
│   ├── runtime.py
│   └── ...
│
├── adapters/               
│   ├── http/              # Общие HTTP адаптеры
│   │   ├── __init__.py
│   │   ├── api_module.py        # FastAPI app
│   │   ├── admin_routes.py      # Admin UI endpoints (много кода)
│   │   ├── operations_routes.py # Operations endpoints
│   │   └── middleware.py        # Auth, CORS, etc
│   │
│   └── storage/           # Outbound адаптеры
│       ├── storage_adapter.py
│       ├── postgresql_adapter.py
│       └── sqlite_adapter.py
│
├── modules/               # Domain modules (тонкие!)
│   ├── admin/
│   │   ├── module.py           # Регистрация runtime services
│   │   └── services.py         # Business logic для admin
│   ├── operations/
│   │   └── handlers.py         # Domain handlers
│   ├── devices/
│   │   ├── module.py
│   │   ├── services.py         # Device domain logic
│   │   └── routes.py           # Только если много domain-specific endpoints
│   └── ...
```

### Правила
1. **Большие generic HTTP endpoints** → `adapters/http/` (admin, operations)
2. **Domain-specific маленькие routes** → `modules/{name}/routes.py`
3. **Все services** → остаются в модулях
4. **Все outbound** → `adapters/storage/`, `adapters/external/`

### Как работает
1. **Общие endpoints** (admin, operations) → живут в `adapters/http/`
2. **Domain routes** (devices, automation) → живут в `modules/`
3. **ApiModule** импортирует оба источника
4. **Модули** регистрируют только services, не HTTP

### Плюсы ✅
- ✅ Прагматичный баланс между чистотой и практичностью
- ✅ Средний рефакторинг (выносим только большие routes)
- ✅ Админские endpoints не раздувают модули
- ✅ Domain routes рядом с domain logic (когда нужно)
- ✅ Понятно, что куда класть

### Минусы ❌
- ❌ Два места для routes (но с чёткими правилами)
- ❌ Не идеальная чистота архитектуры
- ❌ Нужно документировать правила

### Оценка сложности
- **Рефакторинг:** 🟡 Средняя (2-3 часа)
- **Поддержка:** 🟢 Низкая (понятные правила)
- **Масштабируемость:** 🟢 Хорошая

---

## Вариант 4: Минималистичный (Status Quo с улучшениями)

### Структура
```
core-runtime-service/
├── core/                    # Core
│   └── ...
│
├── adapters/               # Только storage
│   ├── postgresql_adapter.py
│   ├── sqlite_adapter.py
│   └── storage_adapter.py
│
├── modules/               # Всё в модулях
│   ├── admin/
│   │   ├── module.py           # 1309 строк → SPLIT на файлы:
│   │   ├── services.py         # Business services
│   │   ├── routes_admin.py     # Admin v1 routes
│   │   ├── routes_operations.py # Operations routes
│   │   ├── routes_proxy.py     # Proxy routes
│   │   └── routes_websocket.py # WS routes
│   └── api/
│       └── module.py           # API Gateway
```

### Как работает
1. **Модуль admin** — разбит на несколько файлов по типу routes
2. **module.py** импортирует все routes и регистрирует
3. **Всё остальное** — без изменений

### Плюсы ✅
- ✅ Минимальные изменения
- ✅ Быстро сделать (30 минут)
- ✅ Работает как сейчас

### Минусы ❌
- ❌ Не решает архитектурную проблему
- ❌ Модули всё равно толстые
- ❌ HTTP код смешан с domain
- ❌ Сложно масштабировать

### Оценка сложности
- **Рефакторинг:** 🟢 Низкая (30 минут)
- **Поддержка:** 🔴 Высокая (временное решение)
- **Масштабируемость:** 🔴 Плохая

---

## Сравнительная таблица

| Критерий | Вариант 1<br>(Hexagonal) | Вариант 2<br>(Module-based) | Вариант 3<br>(Hybrid) | Вариант 4<br>(Status Quo) |
|----------|------------|-------------|----------|------------|
| **Чистота архитектуры** | 🟢🟢🟢 | 🟡🟡 | 🟡🟡🟡 | 🔴 |
| **Сложность рефакторинга** | 🔴🔴🔴 | 🟡🟡 | 🟡🟡 | 🟢 |
| **Простота поддержки** | 🟢🟢🟢 | 🟡🟡 | 🟢🟢 | 🔴🔴 |
| **Тестируемость** | 🟢🟢🟢 | 🟢🟢 | 🟢🟢 | 🟡 |
| **Масштабируемость** | 🟢🟢🟢 | 🟢🟢 | 🟢🟢 | 🔴 |
| **Размер модулей** | 🟢 Тонкие | 🟡 Средние | 🟢 Тонкие | 🔴 Толстые |
| **Время реализации** | 4-6 часов | 2-3 часа | 2-3 часа | 30 минут |

---

## Рекомендация 🎯

### Для production проекта: **Вариант 3 (Hybrid)**

**Почему:**
1. ✅ **Прагматичный баланс** — не перфекционизм, но и не костыль
2. ✅ **Решает главную проблему** — админский модуль перестанет раздуваться
3. ✅ **Умеренный рефакторинг** — 2-3 часа работы
4. ✅ **Понятные правила** — где что класть
5. ✅ **Хорошая масштабируемость** — легко добавлять новые модули

**Правило для команды:**
- **Generic/Admin endpoints** → `adapters/http/`
- **Domain-specific routes** → `modules/{name}/routes.py` (если нужно)
- **Все services** → `modules/{name}/services.py`
- **Outbound** → `adapters/storage/`, `adapters/external/`

---

## Следующие шаги

### Если выбираете Вариант 3 (рекомендуется):

```bash
# 1. Создать структуру
mkdir -p adapters/http
mkdir -p adapters/storage

# 2. Переместить storage adapters
mv adapters/postgresql_adapter.py adapters/storage/
mv adapters/sqlite_adapter.py adapters/storage/
mv adapters/storage_adapter.py adapters/storage/

# 3. Создать HTTP adapters
# - Вынести из modules/admin/module.py → adapters/http/admin_routes.py
# - Вынести operations endpoints → adapters/http/operations_routes.py
# - ApiModule → adapters/http/api_module.py

# 4. Обновить imports
# 5. Тесты
```

### Если выбираете Вариант 1 (идеальный):

Начать с создания `core/ports/` и постепенной миграции.

---

## Заметки

- **AdminModule сейчас: 1309 строк** — это сигнал к рефакторингу
- **ApiModule** — правильно что gateway, но routes должны быть снаружи
- **Operations** — уже правильно в core, handlers в modules/operations/
- **Storage adapters** — уже правильно в adapters/

**Главный вопрос:** Куда класть HTTP routes?
- ❌ **Не в modules** — там domain logic
- ✅ **В adapters/http/** — это inbound adapter
