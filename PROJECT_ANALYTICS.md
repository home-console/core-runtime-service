# Полная аналитика проекта: HomeConsole Core Runtime Service

Дата: 2026-03-30
Объект: `/Users/mihail/projects/HomeConsole/core-runtime-service`
Аналитик: Claude Sonnet 4.6 (cross-verified с кодовой базой)

---

## 1. Что это за проект

Python-платформа исполнения для умного дома с жёстким трёхслойным разделением:

```
core/     (12,360 LOC) — детерминированное ядро, только "как исполнить"
modules/  (42,585 LOC) — вся бизнес-логика
plugins/  (23,465 LOC) — расширения через тонкое API
app/      — композиция, wiring, bootstrap
tests/    (8,000+ LOC) — 40+ тест-файлов
```

**Итого: 113,878 строк Python, 2,359 файлов.**

Ключевые домены: агент-менеджмент, оркестрация устройств (Yandex Smart Home), управление секретами с ротацией, event-driven pipeline, аудит, мультитенантность.

---

## 2. Структура проекта

```
core-runtime-service/
├── core/                           (12,360 LOC — Execution Kernel)
│   ├── runtime/                    runtime.py, _lifecycle.py, config.py, state_engine.py
│   ├── kernel/                     plugin_loader, plugin_manager, plugin_lifecycle, base_plugin, context
│   ├── operations/                 worker, manager, executor, storage
│   ├── messaging/                  InMemoryEventBus (pub/sub, claims, replay)
│   ├── service/                    ServiceRegistry (416 LOC)
│   ├── dependency/                 DependencyResolver (411 LOC)
│   ├── capability/                 CapabilityRegistry, protocol definitions
│   ├── orchestration/              Docker backend — ОСТАТОК, должен быть удалён
│   ├── audit/                      Event logging (559 LOC)
│   ├── observability/              Metrics, health_monitor, rate_limiter
│   ├── adapters/                   SQLite, PostgreSQL storage adapters
│   ├── security/                   MFA, trust, risk management
│   ├── module/                     Module discovery & lifecycle
│   └── http/                       HTTP endpoint registry
│
├── modules/                        (42,585 LOC — Business Logic)
│   ├── admin/                      Control plane, inspector, introspection
│   ├── agent/                      Agent deployment & management (1,580 LOC)
│   ├── api/                        API routing, auth, security
│   ├── auth/                       Authentication handlers (654 LOC)
│   ├── credentials/                Secrets, rotation (740 LOC)
│   ├── devices/                    Device management (698 LOC)
│   ├── execution/                  Operation execution pipeline (575 LOC)
│   ├── marketplace/                Plugin installer (552 LOC)
│   ├── security/                   MFA, trust, risk orchestration
│   ├── policy/                     Policy engine, RBAC
│   ├── operations/                 Operation handlers
│   └── inspector/                  Debugging & introspection (998 LOC)
│
├── plugins/                        (23,465 LOC — Extensions)
│   ├── client-manager-plugin/      Standalone repo с WebSocket сервером (ДУБЛЬ!)
│   ├── client_manager/             In-process client manager (ДУБЛЬ!)
│   ├── yandex_smart_home/          API client (942 LOC)
│   ├── yandex_device_auth/         Device auth flow
│   ├── oauth_yandex/               OAuth provider (1,013 LOC)
│   ├── network_scanner/            Network discovery (нет netifaces — не загрузится)
│   └── test/                       Test plugins
│
├── app/                            (Bootstrap & Composition)
│   ├── bootstrap.py                Runtime assembly, module registration
│   ├── orchestration/              Docker service — ПРАВИЛЬНОЕ место (создан в Wave 6)
│   ├── console.py                  CLI tools
│   └── runtime_monitoring.py
│
└── tests/                          (40+ тест-файлов)
```

---

## 3. Политика ядра (CORE_KERNEL_POLICY_RU.md)

### Золотое правило
> "Если бизнес-логика ('почему') появляется в core — это архитектурный баг. В ядре только 'как исполнить' (pipeline + примитивы)."

### Что РАЗРЕШЕНО в core
- Выполнение шагов пайплайна в фиксированном порядке
- Вызов контрактов (hooks, actions, handlers) без бизнес-решений
- Хранение и возврат результатов исполнения
- Технические примитивы: реестры, event bus, DI-контейнеры, атомарные операции хранилища
- Простые инфраструктурные проверки (валидация входных данных, не политика/routing/retry)

### Что ЗАПРЕЩЕНО в core
- Retry-policy, backoff, решения "повторять/не повторять"
- Интерпретация ошибок и классификация причин отказа
- Routing, выбор провайдера, fallback-стратегии
- Вычисление производных полей (`retry_reason`, `triggered_by` и т.д.)
- Доменная нормализация статусов/ошибок
- **Импорты `modules.*` внутри `core`** (критическая граница)
- Бизнес-логические ветки (кроме технических проверок валидности)
- Roadmap-маркеры в production-коде

### Правило SDK-плагина (5.1)
- Новый код плагинов использует только `runtime.api` / `BasePlugin` helpers
- Запрещён прямой доступ к `plugin_manager`, `module_manager`, orchestration, internal runtime objects

### Приоритет при изменении core
**Удалить логику > Перенести в modules > Расширить core**

---

## 4. Соответствие политике: реальный статус

### Соответствие: **~60%**
- 42 задокументированных нарушения архитектуры
- 11 нарушений P0-P1 (критические/высокий)
- Core имеет 12+ concerns app-уровня
- Граница нарушена в 5+ местах

---

## 5. Архитектурные проблемы по приоритету

### P0 — Критические (риск платформы)

**A1. CoreRuntime как God Object**
- `core/runtime/runtime.py:39` — единая точка для 12+ подсистем: event bus, operations, plugin manager, module manager, storage, HTTP, capability, security, state engine
- Риск: каскадные регрессии, сложный lifecycle, цена любого изменения высокая

**A2. core/orchestration/ не удалён**
- `core/orchestration/docker_backend.py` (448 LOC) и `core/orchestration/service.py` ещё существуют в core
- `app/orchestration/` создан (Wave 6), но старый код не удалён
- Политика нарушена: Docker CLI subprocess management в ядре

**A3. InMemoryEventBus перегружен**
- `core/messaging.py` (452 LOC) совмещает: pub/sub, persistence, claim-lease, middleware, replay
- Должен быть тонкой event bus; стал мультиинструментом

**A4. Глобальные синглтоны**
- `core/observability/metrics.py:257-260` — глобальный registry метрик
- `core/observability/rate_limiter.py:112-115` — глобальный rate limiter
- `core/runtime/operation_context.py:22-29` — глобальный provider операционного контекста
- Риск: изоляция тестов, multi-tenant, order-dependent bugs

**A5. Гибрид event-driven + polling у OperationWorker**
- `core/operations/worker.py:42` — tick() + event subscribe одновременно
- Риск: дублирование работы, сложная диагностика latency

### P1 — Высокий приоритет

**B1. Runtime mutation класса плагина через `setattr(type(...))`**
- `core/kernel/plugin_loader.py:268`
- Модификация class-level поведения во время загрузки
- Риск: побочные эффекты между экземплярами и перезагрузками

**B2. Инъекция полей в instance через `setattr`**
- `core/kernel/plugin_loader.py:250-252`
- Скрытый неформализованный контракт метаданных/зависимостей
- Риск: ошибки совместимости, слабая типобезопасность

**B3. OperationWorker читает контракт через `__dict__` и `getattr`**
- `core/operations/worker.py:62-83`
- Нет формального интерфейса зависимостей
- Риск: latent bugs при рефакторинге runtime-полей

**B4. Прямой доступ к `operations._storage`**
- `core/operations/worker.py:313,319`
- Нарушение инкапсуляции между подсистемами

**B5. DependencyResolver совмещает integrity-check и lifecycle-policy**
- `core/dependency/resolver.py:35,203,293`
- Выходит за рамки "проверки целостности runtime" в сторону lifecycle decisions

**B6. EventBus API неоднородный**
- `core/messaging.py:344,365` — адаптеры, wildcard, completed-awaitable

**B7. String-based backend detection**
- `core/messaging.py:316,322` — `"sqlite" in adapter_name`
- Эвристика вместо capability/protocol

**B8. PluginRuntimeFacade отсутствуют методы**
- `register_http()` и `register_operation_handler()` не проксированы в facade
- Плагины, вызывающие эти методы, упадут при `on_load`

**B9. `kernel_context` Optional без None-guard**
- 30+ мест в runtime обращаются к `kernel_context` без проверки на None
- Падение при рефакторинге

**B10. At-least-once без централизованного dedup**
- `core/operations/worker.py:203`
- Элементы dedup есть, но сквозной гарантийный контракт не унифицирован
- Риск: повторные side effects при частичных сбоях

**B11. `asyncio.gather` без backpressure**
- `core/messaging.py:411` — `return_exceptions=True` без управления нагрузкой
- Риск: cascading overload при burst-событиях

### P2 — Средний приоритет

**C1. 82 вхождения `except Exception`** — системное подавление специфики ошибок

**C2. Silent failures** — `except Exception: pass` без логирования, в т.ч.:
- `core/kernel/plugin_loader.py:114,205`
- `core/runtime/operation_context.py:105`

**C3. Mixed error model** — исключения + `{"ok": False}` dict + строковые ошибки из DependencyResolver

**C4. `print()` и `traceback.print_exc()` в core** — 14 вхождений, bypass observability

**C5. 34 `os.getenv()` в core** — тестируемость страдает, env-зависимость runtime

**C6. PluginLifecycleManager перегружен** (569 LOC) — lifecycle + storage metadata + orchestration + reload

**C7. Hot reload через `importlib.reload`** — хрупко, непредсказуемое состояние модулей

**C8. Конфигурация CORS/CSRF/CSP в core** — app-edge конфигурация в ядре (`core/runtime/config.py`)

**C9. `ModuleManager` слишком широкий** — discovery + import + instance + lifecycle + fallback-логирование

**C10. Backward-compat shims** — `core/orchestration/service.py:228`, `core/runtime/config.py:32`

**C11. Дублирование client_manager** — два плагина с одним `name` в plugin.json

**C12. `network_scanner` неработоспособен** — нет пакета `netifaces`

**C13. Динамический импорт по naming convention** — `core/module.py:298,305`

**C14. Смешение русского и английского** в публичных ошибках/контрактах

---

## 6. Что реально сломано сейчас

| # | Место | Эффект |
|---|-------|--------|
| 1 | `PluginRuntimeFacade` не проксирует `register_http()` / `register_operation_handler()` | Плагины падают при `on_load` |
| 2 | `kernel_context` Optional, 30+ мест без None-guard | Падение при рефакторинге |
| 3 | `RuntimeModule.runtime` может быть None в 18+ модулях | Скрытые crash-точки |
| 4 | `plugins/client-manager-plugin/` + `plugins/client_manager/` — одинаковый `name` | Конфликт при загрузке |
| 5 | `network_scanner` — нет `netifaces` | Плагин не загружается |
| 6 | `core/orchestration/` не удалён после создания `app/orchestration/` | Старый код остался в core |
| 7 | At-least-once без dedup | Дубли side effects при retry |

---

## 7. Что хорошо работает

| Компонент | Статус |
|-----------|--------|
| Plugin manifest loading + топологическая сортировка | Стабильно |
| Storage abstraction (SQLite / PostgreSQL адаптеры) | Стабильно |
| Module discovery и lifecycle | Хорошо изолирован |
| Capability registry и протоколы | Чистая абстракция |
| Security modules (auth, MFA, trust, risk) | Хорошо спроектировано |
| Audit logging framework | Работает |
| Inspector / introspection tools | Работает |
| Service registry и dependency resolution | Работает |
| Event bus pub/sub для in-process коммуникации | Работает |
| 40+ тест-файлов (Wave 4-6 рефакторинги) | Систематически |

---

## 8. Метрики готовности по слоям

| Компонент | Готовность | Комментарий |
|-----------|-----------|-------------|
| Core execution kernel | 85% | Граница drift, god object |
| Module system | 90% | Хорошо изолирован |
| Plugin system | 75% | Facade неполная |
| Storage abstraction | 90% | Адаптеры стабильны |
| Operations execution | 80% | At-least-once риск |
| Security modules | 85% | Хорошо спроектировано |
| Observability | 70% | Singleton, не injectable |
| Test coverage | 75% | Gaps в интеграции |
| Doc coverage | 60% | Policy хорошая, API docs нет |
| **Соответствие Policy** | **60%** | 42 нарушения, 11 P0-P1 |
| **Production readiness** | **65-70%** | Работает, но хрупко |
| **Общая completeness** | **75-78%** | — |

---

## 9. Прогресс рефакторинга (Wave 1-6)

| Волна | Статус | Результат |
|-------|--------|-----------|
| Wave 1-3 | ✅ Завершено | Legacy cleanup |
| Wave 4 | ✅ Завершено | Interface extraction, 39+ regression tests |
| Wave 5 | ✅ Завершено | Package structure reorg, backward compat |
| Wave 6 | 🔄 В процессе (2/4) | runtime.py split ✅, secure_storage.py split ✅ |

**Ещё не сделано в Wave 6:**
- Split `core/service_registry.py` (529 LOC)
- Split `core/capability_registry.py` (497 LOC) или `core/http_registry.py` (441 LOC)
- Удаление `core/orchestration/` после переноса в `app/orchestration/`

---

## 10. Приоритеты следующих действий

### Срочно (эта неделя)
```
1. Добавить register_http() / register_operation_handler() в PluginRuntimeFacade
2. None-guard для kernel_context во всех 30+ местах
3. Удалить core/orchestration/ (код перенесён в app/orchestration/)
4. Устранить дублирование client_manager плагина
```

### Wave 7 (ближайший спринт)
```
5. Убрать глобальные синглтоны (metrics, rate_limiter, operation_context) → явный DI
6. Унифицировать error contract (единый Result type или exception hierarchy)
7. Удалить print() / traceback.print_exc() из core → structured logging
8. Split core/service_registry.py, core/capability_registry.py
```

### Wave 8 (среднесрочно)
```
9. Декомпозировать PluginLifecycleManager (569 LOC) на узкие компоненты
10. Ввести строгие протоколы вместо __dict__/getattr в OperationWorker
11. Configuration object injection (убрать os.getenv из core)
12. Dedup layer для at-least-once operations
13. Документация runtime.api для SDK-плагинов
```

### Wave 9+ (долгосрочно)
```
14. Декомпозировать CoreRuntime — не должен содержать 12+ подсистем
15. Явный DI-контейнер
16. Безопасный plugin hot-reload (без importlib.reload)
17. Вынести CORS/CSRF/CSP config из core в app-edge
18. Формальный observability contract (не singleton)
```

---

## 11. Итоговая оценка

**Оценка: C+ / B-**

**Сильные стороны:**
- Архитектурное намерение чёткое и задокументированное
- Модульная система хорошо изолирована
- Storage abstraction работает
- Security modules зрелые
- Систематический Wave-подход к рефакторингу
- 40+ тест-файлов

**Слабые стороны:**
- God Object CoreRuntime
- core/orchestration/ не удалён (незавершённая миграция)
- Глобальные синглтоны ухудшают тестируемость
- Dynamic contracts (getattr, setattr, importlib) снижают типобезопасность
- PluginRuntimeFacade неполная — плагины могут падать
- Mixed error model усложняет диагностику

**До 90%+ соответствия политике:** ~8-12 недель системной работы, продолжая Wave-подход.

**Большинство проблем — boundary drift, а не фундаментальные ошибки дизайна. Всё решаемо без переписывания.**
