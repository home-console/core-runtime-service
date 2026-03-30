# Глобальные архитектурные проблемы ядра

Дата актуализации: 2026-03-30
Объект анализа: `core/` (execution kernel)
Верифицировано по коду (Claude Sonnet 4.6)

---

## 1. Краткая сводка

Ядро существенно продвинуто по сравнению с legacy-версией (Waves 4-6), но сохраняет системные архитектурные риски:

- Высокая концентрация ответственности в runtime/kernel слоях (God Object CoreRuntime).
- Незавершённая граница `core` vs app (`core/orchestration/` не удалён).
- Высокая доля динамических контрактов (`getattr`, `__dict__`, `importlib`, mutation классов/свойств).
- Непоследовательная модель ошибок (исключения + `{"ok": False}` + массовое подавление).
- Глобальные синглтоны (metrics, rate_limiter, operation context) ухудшают предсказуемость и тестируемость.

---

## 2. Объективные метрики

- Python-кода в `core`: 12,360 строк.
- Крупнейшие файлы в core:
  - `core/kernel/plugin_lifecycle.py`: 569 LOC
  - `core/audit/events.py`: 559 LOC
  - `core/adapters/sqlite_adapter.py`: 461 LOC
  - `core/messaging.py`: 452 LOC
  - `core/orchestration/docker_backend.py`: 448 LOC ← **должен быть удалён** (перенесён в app)
  - `core/kernel/base_plugin.py`: 427 LOC
  - `core/service/registry.py`: 416 LOC
  - `core/dependency/resolver.py`: 411 LOC
  - `core/operations/worker.py`: 406 LOC
  - `core/module.py`: 397 LOC
- Вхождений `except Exception`: 82.
- Вхождений `print(...)` в `core`: 14.
- Вхождений `os.getenv(...)` в `core`: 34.
- Вхождений мутации `sys.modules` в `core`: 1 (plugin_loader — приемлемо после фикса sys.path).
- Вызовов `asyncio.create_subprocess_exec(...)` в `core`: 9 (в core/orchestration/ — подлежит удалению).

---

## 3. Актуальные проблемы архитектуры

От критичных к средним. Все пункты верифицированы по коду на 2026-03-30.

### A. Нарушения границ слоя ядра (Core Boundary Drift)

**A1. `core/orchestration/` не удалён после переноса в `app/orchestration/`** ✅ **ИСПРАВЛЕНО** (2026-03-30)
- Evidence: `core/orchestration/docker_backend.py`, `core/orchestration/service.py`
- Проблема: `app/orchestration/` создан (Wave 6), но оригиналы в core остались. Два источника истины.
- Риск: путаница при импортах, старый код продолжает быть частью core.
- Действие: удалить `core/orchestration/docker_backend.py` и `core/orchestration/service.py`.
- **Решение:** Файлы `core/orchestration/` удалены. `core/runtime/runtime.py` обновлён для импорта из `app.orchestration` через TYPE_CHECKING.

**A2. CORS/CSRF/CSP конфигурация живёт в core**
- Evidence: `core/runtime/config.py:233`, `core/runtime/config.py:265`, `core/runtime/config.py:275`
- Проблема: параметры web-edge безопасности принадлежат app-layer, не минимальному kernel.
- Риск: усложнение переносимости ядра в headless-сценариях.

**A3. CoreRuntime хранит app-level extension hooks**
- Evidence: `core/runtime/runtime.py:121`, `core/runtime/runtime.py:123`
- Проблема: поля для app-level фабрик/прокси в ядре.
- Риск: нарушение инверсии зависимостей, drift к сервис-локатору.

**A4. Гидратация app-defined префиксов состояния в lifecycle ядра**
- Evidence: `core/runtime/runtime.py:136`, `core/runtime/_lifecycle.py:114`
- Проблема: ядро принимает решение по boot-time восстановлению данных на основе внешних namespace-конвенций.
- Риск: скрытая доменная политика в core start-пути.

### B. Монолитность и высокая связность

**B1. `CoreRuntime` как God Object / композиционный центр всего ядра** ✅ **ИСПРАВЛЕНО** (2026-03-30)
- Evidence: `core/runtime/runtime.py:39-160`
- Проблема: единая точка с 12+ подсистемами: event bus, operations, plugin manager, module manager, storage, HTTP, capability, security, state engine.
- Риск: дорогие изменения, каскад регрессий, сложный lifecycle.
- **Решение:** Проведена декомпозиция на 5 специализированных компонентов:
  1. `CoreServices` — базовые сервисы (storage, vault, event_bus, service_registry, state_engine, http)
  2. `CapabilityComponent` — security и capabilities
  3. `PluginInfrastructure` — плагины и модули (plugin_manager, module_manager, dependency_resolver, integrations)
  4. `OperationsComponent` — операции и execution (manager, worker, execution_controller)
  5. `RuntimeMonitor` — monitoring, health checks, metrics
  - `CoreRuntime.__init__` сокращён с ~70 строк до ~20
  - Обратная совместимость сохранена через property-методы

**B2. `PluginLifecycleManager` перегружен (lifecycle + storage metadata + orchestration + reload)**
- Evidence: `core/kernel/plugin_lifecycle.py:1`, `:172`, `:315`
- Проблема: 4-5 зон ответственности в одном классе (569 LOC).
- Риск: SRP-нарушение, сложные тесты, неочевидные инварианты.

**B3. `InMemoryEventBus` совмещает pub/sub, persistence, claim-lease, middleware и replay**
- Evidence: `core/messaging.py:113`, `:130`, `:312`
- Проблема: тяжёлый центр событийной шины с разнородной логикой (452 LOC).
- Риск: сложно гарантировать корректную доставку и консистентность семантик.

**B4. `DependencyResolver` совмещает integrity-check и lifecycle-policy**
- Evidence: `core/dependency/resolver.py:35`, `:203`, `:293`
- Проблема: resolver выходит за рамки "проверки целостности runtime" в lifecycle-decisions.
- Риск: размытие границ между ядром и orchestration/domain governance.

**B5. `ModuleManager` слишком широкий**
- Evidence: `core/module.py:176`, `:298`, `:305`
- Проблема: discovery + import + instance + lifecycle + fallback-логирование в одном компоненте.
- Риск: хрупкость при развитии модульной модели.

### C. Динамические и хрупкие контракты

**C1. Runtime mutation класса плагина через `setattr(type(...))`**
- Evidence: `core/kernel/plugin_loader.py:268`
- Проблема: модификация class-level поведения во время загрузки.
- Риск: побочные эффекты между экземплярами и перезагрузками.

**C2. Инъекция runtime-полей в plugin instance через `setattr`**
- Evidence: `core/kernel/plugin_loader.py:250`, `:252`
- Проблема: неформализованный скрытый контракт метаданных/зависимостей.
- Риск: ошибки совместимости, слабая типобезопасность.

**C3. `OperationWorker` читает контракт через `__dict__` и `getattr`**
- Evidence: `core/operations/worker.py:62`, `:69`, `:83`
- Проблема: нет формального интерфейса зависимостей.
- Риск: latent bugs при рефакторинге runtime-полей.

**C4. Прямой доступ к private/internal полям других компонентов** ✅ **ИСПРАВЛЕНО** (2026-03-30)
- Evidence: `core/operations/worker.py:313`, `:319` (обращение к `operations._storage`)
- Проблема: нарушение инкапсуляции.
- Риск: сильная связность, хрупкие инварианты.
- **Решение:** Добавлены публичные методы в `OperationManager`: `persist_operation()`, `ensure_attempt_created()`, `try_claim_attempt()`, `get_attempt()`, `persist_attempt()`, `get_executor()`. `OperationWorker` обновлён для использования публичного API вместо прямого доступа к `_storage` и `_executor`.

**C5. Сигнатуры EventBus подписки неоднородны**
- Evidence: `core/messaging.py:344`, `:365`
- Проблема: адаптеры, wildcard, completed-awaitable — разные модели в одном API.
- Риск: когнитивная сложность, ошибки интеграции.

**C6. String-based backend detection в EventBus**
- Evidence: `core/messaging.py:316`, `:322` — `"sqlite" in adapter_name`
- Проблема: строковая эвристика вместо capability/protocol.
- Риск: ломкость при переименовании/замене адаптеров.

**C7. Динамический импорт модулей по naming convention**
- Evidence: `core/module.py:298`, `:305`
- Проблема: неявная связь имени модуля и class-name правила.
- Риск: слабая диагностика, ошибки обнаружения.

**C8. `PluginRuntimeFacade` не проксирует критические методы** ← СЛОМАНО СЕЙЧАС
- Методы `register_http()` и `register_operation_handler()` отсутствуют в facade.
- Плагины, вызывающие эти методы, упадут при `on_load`.

**C9. `kernel_context` Optional без None-guard** ← СЛОМАНО СЕЙЧАС
- 30+ мест в runtime обращаются к `kernel_context` без проверки None.
- Падение при рефакторинге или None-инициализации.

### D. Модель ошибок и наблюдаемость

**D1. Высокая плотность broad exception handling** ← P0
- Evidence: `core/runtime/_lifecycle.py:235`, `core/kernel/plugin_loader.py:323`, `core/dependency/resolver.py:53`, `core/module.py:325`
- 82 вхождения `except Exception` — системное подавление специфики ошибок.
- Риск: деградация диагностики, скрытые дефекты в production.

**D2. Silent failures — подавление без сигнализации**
- Evidence: `core/kernel/plugin_loader.py:114`, `:205`, `core/runtime/operation_context.py:105`
- `except Exception: pass` — ошибки теряются полностью.
- Риск: неотлаживаемые production-сбои.

**D3. Mixed error model: исключения + `{"ok": False}` dict + строки**
- Evidence: `core/orchestration/docker_backend.py:120`, `:125`; `core/dependency/resolver.py:78`
- Нет единого error contract.
- Риск: неоднозначное поведение клиентов.

**D4. Fallback на `print()` и `traceback.print_exc()` в core** ✅ **ИСПРАВЛЕНО** (2026-03-30)
- Evidence: `core/module.py:176`, `:213`, `:259`; `core/runtime/_lifecycle.py:93`
- Bypass observability pipeline.
- Риск: потеря контекста, шум в stderr, нарушение единого лог-контракта.
- **Решение:** Все `print()` в коде core заменены на `logger.exception()` и `logger.warning()`. `traceback.print_exc()` удалён из `_lifecycle.py`. Легитимный fallback в `logger_helper.py` сохранён (для случаев до инициализации runtime).

### E. Глобальное состояние

**E1. Глобальный singleton registry метрик**
- Evidence: `core/observability/metrics.py:257-260`
- Shared mutable state на процесс, нет injectable альтернативы.

**E2. Глобальный singleton rate limiter**
- Evidence: `core/observability/rate_limiter.py:112-115`
- Некорректная изоляция tenant/runtime.

**E3. Глобальный provider operation context**
- Evidence: `core/runtime/operation_context.py:22-29`
- Race/scope проблемы при нескольких runtime/тестовых окружениях.

### F. Plugin lifecycle риски

**F1. Сильная связь plugin lifecycle с orchestration внутри core**
- Evidence: `core/kernel/plugin_lifecycle.py:172`, `:243`
- Трудно отделить in-process plugin lifecycle от infra orchestration.

**F2. Metadata плагинов "зашита" в lifecycle manager**
- Evidence: `core/kernel/plugin_lifecycle.py:315`, `:360`
- Storage schema (`plugins.metadata`) жёстко связана с lifecycle.

**F3. Hot reload через `importlib.reload` и path-эвристику**
- Evidence: `core/kernel/plugin_lifecycle.py:449`, `:516`
- Горячая перезагрузка хрупка, непредсказуемое состояние модулей после reload.

**F4. Backward-compat shims в production-пути**
- Evidence: `core/orchestration/service.py:228`, `core/runtime/config.py:32`
- Временные ветки совместимости закреплены в runtime.

### G. Event/Operation execution

**G1. At-least-once без централизованного dedup** ← P0 по последствиям
- Evidence: `core/operations/worker.py:203`, `core/messaging.py:177`
- Элементы dedup есть, но сквозной гарантийный контракт не унифицирован.
- Риск: повторные side effects при сбоях (webhook, команды, внешние вызовы).

**G2. `asyncio.gather` без backpressure-политики**
- Evidence: `core/messaging.py:411` — `return_exceptions=True` без управления нагрузкой.
- Риск: cascading overload при burst-событиях.

**G3. Operation context делает app-level вызовы**
- Evidence: `core/runtime/operation_context.py:94`, `:107`, `:124`
- Context helper становится app-aware (вызывает сервисы логгера).
- Риск: скрытая зависимость ядра от наличия/поведения определённых сервисов.

### H. Конфигурация и portability

**H1. Высокая env-зависимость ядра**
- Evidence: `core/runtime/config.py:233`, `:284` — 34 вхождения `os.getenv` в core.
- Риск: нестабильность поведения между окружениями, сложность тестирования.

**H2. `DockerOrchestrationBackend._find_project_root` — path-эвристика**
- Evidence: `core/orchestration/docker_backend.py:39` (файл подлежит удалению вместе с переносом)
- Поиск корня проекта по набору папок — non-deterministic в CI/mono-repo.

**H3. Docker CLI через subprocess вместо типизированного порта**
- Evidence: `core/orchestration/docker_backend.py:64`, `:425` (файл подлежит удалению)
- Парсинг stderr/stdout как API, platform-specific сбои.

---

## 4. Приоритетная матрица

```
P0 (архитектурный риск платформы — чинить первым):
  ✅ B1 (God Object CoreRuntime) — ИСПРАВЛЕНО 2026-03-30
  D1 (82x except Exception)
  G1 (at-least-once без dedup)
  C8 (PluginFacade — методы сломаны, плагины падают)
  ✅ A1 (core/orchestration/ не удалён) — ИСПРАВЛЕНО 2026-03-30
  ✅ C4 (доступ к _storage) — ИСПРАВЛЕНО 2026-03-30
  ✅ D4 (print/traceback в core) — ИСПРАВЛЕНО 2026-03-30

P1 (высокий приоритет):
  A2, A3, B2, B3, B4, C1, C2, C3, C9, D2, D3, E1, E2, E3, F1, F2, G2

P2 (средний приоритет):
  A4, B5, C5, C6, C7, F3, F4, G3, H1, H2, H3
```

---

## 5. Рекомендуемая программа исправления

**Волна A — Boundary Hardening (Wave 7):**
- Удалить `core/orchestration/docker_backend.py` и `core/orchestration/service.py`.
- Убрать global singletons (metrics, rate_limiter, operation_context) → явный DI.
- Добавить `register_http()` / `register_operation_handler()` в PluginRuntimeFacade.
- None-guard для `kernel_context` во всех 30+ местах.

**Волна B — Contract Hardening (Wave 8):**
- Убрать class-level mutation из plugin loader (C1, C2).
- Ввести строгие протоколы для OperationWorker вместо `__dict__`/`getattr` (C3).
- Запретить прямой доступ к private полям других подсистем (C4).
- Унифицировать error contract (единый Result type или exception hierarchy).

**Волна C — Error/Observability Unification (Wave 8):**
- Сократить `except Exception`, запретить silent `pass` в критичных путях.
- Удалить `print()`/`traceback.print_exc()` из core.
- Configuration object injection (убрать `os.getenv` из core).

**Волна D — Decomposition (Wave 9):**
- Декомпозировать `PluginLifecycleManager`, `InMemoryEventBus`, `DependencyResolver`, `ModuleManager`.
- Упростить `CoreRuntime` до orchestration-free kernel coordinator.
- Dedup layer для at-least-once operations.
- Безопасный hot-reload без `importlib.reload`.

---

---

## ✅ Выполнено

Задачи удалены из активного списка. Зафиксировано для истории.

---

### ✅ Удаление core/orchestration/ после переноса в app (2026-03-30)

**Изначальная проблема:**
`core/orchestration/` не удалён после переноса в `app/orchestration/`. Два источника истины, риск путаницы при импортах.

**Что сделано:**
- Файлы `core/orchestration/docker_backend.py` и `core/orchestration/service.py` удалены.
- `core/runtime/runtime.py` обновлён для импорта из `app.orchestration` через TYPE_CHECKING.
- Граница ядра закрыта — оркестрация полностью в app-layer.

---

### ✅ Устранение print() и traceback.print_exc() из core (2026-03-30)

**Изначальная проблема:**
14 вхождений `print()` и `traceback.print_exc()` в core — bypass observability pipeline.

**Что сделано:**
- `core/module.py`: 4 `print()` заменены на `logger.exception()`.
- `core/adapters/sqlite_adapter.py`: 2 `print()` заменены на `logger.warning()`.
- `core/runtime/_lifecycle.py`: `traceback.print_exc()` удалён.
- Легитимный fallback в `logger_helper.py` сохранён (для случаев до инициализации runtime).
- `print()` в docstring сохранены (как примеры использования API).

---

### ✅ Запрет доступа к private полям (нарушение инкапсуляции) (2026-03-30)

**Изначальная проблема:**
`OperationWorker` напрямую обращался к `operations._storage` и `operations._executor` — нарушение инкапсуляции.

**Что сделано:**
- Добавлены публичные методы в `OperationManager`: `persist_operation()`, `ensure_attempt_created()`, `try_claim_attempt()`, `get_attempt()`, `persist_attempt()`, `get_executor()`.
- `OperationWorker` обновлён для использования публичного API.
- Прямой доступ к `_storage` и `_executor` из worker устранён.

---

### ✅ Вынос оркестрации из CoreRuntime как явная зависимость (2026-03-30, ЗАВЕРШЕНО)

**Изначальная проблема:**
`CoreRuntime` сам собирал orchestration backend — знал про Docker-реализацию и был platform-composition слоем. Нарушение золотого правила политики ядра.

**Что реально сделано:**
- `orchestration_service` теперь является инжектируемым параметром `CoreRuntime.__init__(orchestration_service: Optional[OrchestrationService] = None)`.
- `app/orchestration/` создан с `DockerOrchestrationBackend` и `OrchestrationService` — правильное место для этого кода.
- `CoreRuntime` использует `TYPE_CHECKING` import — нет runtime-зависимости от Docker-реализации.
- Метод `_build_default_orchestration_service()` удалён из ядра.
- **2026-03-30:** `core/orchestration/` полностью удалён. Задача завершена.

---

### ✅ Устранение мутации `sys.path` при загрузке плагинов (2026-03-29)

**Изначальная проблема:**
Глобальное изменение import resolution через `sys.path` во время загрузки плагина. Race-condition при параллельных операциях, трудноуловимые конфликты импортов.

**Что сделано:**
- `plugin_loader` теперь использует `importlib.util.spec_from_file_location` для явной загрузки модуля по пути — `sys.path` не мутируется.
- Модули регистрируются в `sys.modules` — это норма, необходимо для корректной работы импортов внутри плагина.

**Статус:** полностью закрыто. `sys.modules` мутация остаётся и это правильно.
