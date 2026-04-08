# Глобальные архитектурные проблемы ядра (`core/`)

**Актуализация:** 2026-04-06  
**Объект:** каталог `core/` (runtime, kernel, operations, messaging, adapters).  
**Метрики:** пересчитаны по рабочей копии репозитория (не зафиксированы в CI).

**Связанные документы**

| Документ | Назначение |
|----------|------------|
| [modules_plugins_problems.md](modules_plugins_problems.md) | Граница modules ↔ plugins, сервисы, контракты |

---

## Оглавление

1. [За 60 секунд](#1-за-60-секунд)  
2. [Метрики](#2-метрики)  
3. [Открытые проблемы](#3-открытые-проблемы)  
4. [Приоритеты](#4-приоритеты)  
5. [Рекомендуемые шаги](#5-рекомендуемые-шаги)  
6. [Реестр закрытых пунктов](#6-реестр-закрытых-пунктов)  
7. [Архив решений (подробности)](#7-архив-решений-подробности)

---

## 1. За 60 секунд

- После волн 4–6 ядро **существенно разгружено**: удалён `core/orchestration/` (оркестрация в `app/orchestration/`), `CoreRuntime` декомпозирован, `InMemoryEventBus` и `PluginLifecycleManager` разнесены по компонентам, плагин-лоадер и operation worker получили более явные контракты.
- **Стало лучше (D1 закрыт):** в `core/` устранён `except Exception` (метрика — 0), введены allowlist-группы ошибок и инварианты по `asyncio.CancelledError`; от регрессий защищает тест `tests/test_core_exception_policy.py`.
- **По-прежнему системные риски:** смешение моделей ошибок и **многоуровневые boundary-политики**, **динамические контракты** (`getattr`, соглашения об имёновании), **глобальные accessor’ы** метрик/лимитов/operation context (частично компенсированы `RuntimeContext`, legacy остаётся), **сложность plugin lifecycle / hot-reload**.
- **At-least-once / dedup:** контракт формализован (**G1** закрыт): `core/operations/dedup_contract.py`, ADR `docs/adr/001-dedup-at-least-once-contract.md`, контракт события `docs/event_contracts/operation_ready.md`.

---

## 2. Метрики

*Пересчёт 2026-04-06.*

| Метрика | Значение |
|---------|----------|
| Строк Python в `core/` | ~14 700 |
| Строк с подстрокой `except Exception` (`rg`, все вхождения в строке) | 0 |
| Вхождений `os.getenv(` в `core/` | 0 |
| Вхождений мутации `sys.modules` (кроме ожидаемой регистрации модулей плагина) | см. `plugin_loader` |

**Крупнейшие файлы `core/` (LOC):**

1. `core/audit/events.py` — 559  
2. `core/operations/worker.py` — 464  
3. `core/kernel/base_plugin.py` — 464  
4. `core/adapters/sqlite_adapter.py` — 461  
5. `core/kernel/plugin_lifecycle.py` — 438  
6. `core/service/registry.py` — 416  
7. `core/module.py` — 380  
8. `core/runtime/_lifecycle.py` — 455  
9. `core/runtime/runtime.py` — 373  
10. `core/kernel/plugin_loader.py` — 357  

> Папки **`core/orchestration/`** в дереве **нет** (перенос в `app/orchestration/`). Упоминания `docker_backend` в контексте **core** в этом документе считаются устаревшими; реализация — в app-слое.

---

## 3. Открытые проблемы

Ниже только то, что **по смыслу ещё не закрыто** или требует **дальнейшей формализации**. Закрытые пункты — в [§6](#6-реестр-закрытых-пунктов).

### A. Границы ядра

*(все пункты раздела закрыты; см. [§6](#6-реестр-закрытых-пунктов))*

### B. Монолитность и связность

*(все пункты раздела закрыты; см. [§6](#6-реестр-закрытых-пунктов))*

### C. Динамические контракты

*(все пункты раздела закрыты; см. [§6](#6-реестр-закрытых-пунктов))*

### D. Ошибки и наблюдаемость

*(пункты раздела закрыты; см. [§6](#6-реестр-закрытых-пунктов))*
 
### E. Глобальное состояние

*(все пункты раздела закрыты; см. [§6](#6-реестр-закрытых-пунктов))*

### F. Plugin lifecycle

**F2. Метаданные плагинов и схема storage** — **закрыто (2026-04-06)**  
- **Сделано:** введён явный контракт хранения метаданных: `core/kernel/plugin_metadata_storage_contract.py` (namespace, schema_version, нормализация), `PluginStorageManager` пишет/читает только по контракту.  
- **Тест:** `tests/test_plugin_metadata_storage_contract.py`.

**F3. Hot reload** — **закрыто (2026-04-06)**  
- `importlib.reload` в `core/` отсутствует (reload = stop→unload→load fresh→start).  
- Хрупкая эвристика `Path(__file__).parent.parent.parent / "plugins"` удалена из `plugin_lifecycle.py` и `plugin_manager.py`; вместо неё — `_resolve_plugins_dir()` из `Config.plugins_dir`; при отсутствии конфига — `ValueError` / graceful return.

**F4. Backward-compat shims в горячих путях** — **закрыто (2026-04-06)**  
- **Удалено:** `DependencyResolver` facade (`core/dependency/resolver.py`) и все его использования в core/tests; остались только явные компоненты `DependencyIntegrityChecker` и `PluginLifecyclePolicy`.  
- **Переведено:** app-layer мониторинг больше не использует `runtime.runtime_health_check` / `runtime.runtime_metrics_collector`; теперь делегаты устанавливаются через `runtime.monitor.*_delegate`. Fallback-ветки в `core/runtime/_lifecycle.py` удалены.  
- **Упрощено:** `OperationWorker` больше не дублирует проверку “обработано ли событие” через event_bus — только централизованный `DedupLayer` + claim через event bus.

### G. Исполнение операций и событий

**G1. At-least-once и единый dedup-контракт** — **закрыто (2026-04-05)**  
- **Код:** `core/operations/dedup_contract.py` — namespace, префиксы ключей, TTL, `OPERATION_READY_EVENT_TYPE`, билдеры ключей; `DedupLayer` и издатели события используют только этот контракт.  
- **Документация:** [docs/adr/001-dedup-at-least-once-contract.md](docs/adr/001-dedup-at-least-once-contract.md), [docs/event_contracts/operation_ready.md](docs/event_contracts/operation_ready.md); TypedDict `OperationReadyPayload` в `core/events_schemas.py`.  
- **Тесты:** `tests/test_dedup_contract.py` (регрессия формата ключей).

### H. Конфигурация и переносимость

**H1. Высокая env-зависимость ядра** — **закрыто (2026-04-06)**  
- **Сделано:** в `core/` устранён `os.getenv` (парсинг env сосредоточен в boundary-хелперах `Config.from_env(env=...)` и `SecurityConfig.from_env(env=...)`, с возможностью передать mapping; плагинный helper читает `os.environ` локально).  
- **Метрика:** вхождений `os.getenv(` в `core/` — **0** (см. §2).

**H2–H3. Docker / path-эвристики / subprocess** — **закрыто (2026-04-06)**  
- **Сделано:** platform/CLI детали и orchestration-реализация вынесены в app-layer (`app/orchestration/`); ядро не содержит Docker-кода и не принимает решений об окружении.  
- **Evidence:** `core/orchestration/` отсутствует; сборка orchestration происходит в `app/bootstrap.py` (а также CLI в `app/console.py`).

### I. Capability protocol

**I1. `ProviderMetadata`: `__post_init__`-нормализация Optional полей** — **закрыто (2026-04-06)**  
- **Сделано:** `timeouts`/`capabilities` переведены на `field(default_factory=...)`, `__post_init__` удалён; типы больше не “врут” про `Optional`.  
- **Файл:** `core/capability/protocol.py`.

---

## 4. Приоритеты

| Уровень | Смысл | Открытые ориентиры |
|---------|--------|---------------------|
| **P0** | Риск для корректности/диагностики платформы | — |
| **P1** | Структурный долг, связность | — |
| **P2** | Когнитивная сложность, переносимость | — |

Ранее в документе фигурировала формулировка «P0 16/16 закрыто» — она **противоречила** оставшимся пунктам и вводила в заблуждение. Актуальная матрица — таблица выше; закрытые идентификаторы — в [§6](#6-реестр-закрытых-пунктов).

---

## 5. Рекомендуемые шаги

1. **F3:** заменить path-эвристику в `plugin_lifecycle.py:reload_plugin` на явный `plugins_dir` из конфига (убрать `Path(__file__).parent.parent.parent`).  
2. **Метрики:** периодически обновлять §2 скриптом (или CI job) чтобы не копить расхождение с кодом.

---

## 6. Реестр закрытых пунктов

Компактная фиксация; детали — [§7](#7-архив-решений-подробности).

| ID | Тема | Период |
|----|------|--------|
| A1 | Удаление `core/orchestration/`, импорты через `app.orchestration` | 2026-03-30 |
| A2 | CORS/CSRF/CSP вынесены в `SecurityConfig` | 2026-03-30 |
| A3 | App extension hooks → `AppExtensionConfig` | 2026-03-30 |
| A4 | Гидратация state: app-layer callback вместо `critical_state_prefixes` как core-политики (legacy fallback сохранён) | 2026-04-06 |
| B1 | Декомпозиция `CoreRuntime` (CoreServices, компоненты) | 2026-03-30 |
| B2 | Выделение `PluginStorageManager` / `PluginOrchestrationManager` | 2026-03-30 |
| B3 | Выделение `EventBusStorageManager` / `EventBusClaimManager` | 2026-03-30 |
| B4 | `DependencyResolver` стал facade: integrity-check и lifecycle-policy вынесены в отдельные компоненты (`integrity_checker`, `lifecycle_policy`) | 2026-04-06 |
| B5 | `ModuleManager` разгружен: discovery и dependency-ordering делегированы в `ModuleDiscovery`/`ModuleDependencySorter` | 2026-04-06 |
| C1–C2 | `PluginContext` / manifest вместо мутации класса и скрытой инъекции | 2026-03-30 |
| C3 | `WorkerDependencies` вместо разбора через `__dict__` | 2026-03-30 |
| C4 | Публичный API `OperationManager` вместо `_storage` / `_executor` | 2026-03-30 |
| C8 | `PluginRuntimeFacade`: `register_http`, `register_operation_handler` | ранее |
| C9 | Инициализация `kernel_context` в `CoreRuntime.__init__` | ранее |
| C6 | EventBus: удалены string-based эвристики backend detection (feature/capability detection вместо `"sqlite" in ...`) | 2026-04-06 |
| C7 | ModuleDiscovery: логирование стратегии resolution, warning на camelCase fallback, `list_available_modules()` в ошибке | 2026-04-06 |
| C6-glob | EventBus: глобальный `_event_handler_semaphore` перенесён в per-instance `InMemoryEventBus._handler_semaphore` | 2026-04-06 |
| C5 | EventBus: нормализованы обработчики подписок (typed/simple для конкретных event_type и wildcard), unsubscribe работает с исходным handler | 2026-04-06 |
| F1 | Plugin lifecycle: orchestration вынесена за менеджер/порт; lifecycle не решает container-details и не читает orchestration_service напрямую | 2026-04-06 |
| F2 | Plugin metadata storage: контракт `plugins.metadata` (schema_version + нормализация) и тест; `PluginStorageManager` больше не держит “свободный dict” | 2026-04-06 |
| F3 | Hot reload: эвристика `Path(__file__).parent.parent.parent` удалена из `plugin_lifecycle.py` и `plugin_manager.py`; явный `_resolve_plugins_dir()` из `Config.plugins_dir` | 2026-04-06 |
| I1 | Capability protocol: `ProviderMetadata` использует `default_factory` вместо `__post_init__`-нормализации Optional | 2026-04-06 |
| F4-hydration | State hydration: удалён `_hydrate_critical_state_legacy()`; только app-layer callback | 2026-04-06 |
| H2–H3 | Environment/orchestration: Docker/path/subprocess вынесены в app-layer (`app/orchestration`, CLI); ядро не содержит platform-логики | 2026-04-06 |
| D2 | Замена голого `except: pass` на логирование | 2026-03-30 |
| D3 | Тип `Result` / `Err` в resolver (и совместимость) | 2026-03-30 |
| D4 | Уход от `print` / `traceback.print_exc` в пользу логгера | 2026-03-30 |
| D1 | Исключения в `core/`: устранён `except Exception`, введены allowlist-группы и правила `CancelledError`; добавлен guard-тест, предотвращающий регрессии (`tests/test_core_exception_policy.py`) | 2026-04-06 |
| G2 | Семафор / ограничение параллелизма обработчиков событий | 2026-03-30 |
| G3 | `OperationLogger` protocol, ядро не зовёт `logger.log` напрямую | 2026-03-30 |
| G1 | Единый dedup/at-least-once контракт: `dedup_contract`, ADR 001, `operation_ready` contract | 2026-04-05 |
| E1–E3 | Глобальные синглтоны `MetricsRegistry`/`PluginRateLimiter` удалены; DI через `RuntimeContext`; `get_*()` accessor'ы полностью убраны | 2026-04-04 |
| PR-3 | Все silent `except Exception` в модулях и handlers получили `logger.warning/error(..., exc_info=True)` | 2026-04-04 |
| PR-4 | SDK-фасад: плагины импортируют `from sdk.plugin_ext import BasePlugin` вместо `core.kernel.*`; `sdk/http.py`, `sdk/operation.py`, `sdk/events.py` | 2026-04-04 |
| PR-5 | `client-manager-plugin`: все `os.getenv()` централизованы в `Settings` dataclass + `get_settings()` | 2026-04-04 |
| PR-6 | Модули переведены с `self.runtime.*` на `self.context.*` (operations, storage, service_registry, capability_registry, event_bus); `event_bus` добавлен в `RuntimeContext` | 2026-04-04 |
| — | Capability registry: аргументы `register_provider`, consumers, `start_plugin` | 2026-04-02 |
| — | Подпись `BasePlugin` в тестах (`runtime_or_context`) | 2026-04-02 |
| — | `OperationsComponent.execute()` для обратной совместимости | 2026-04-02 |
| — | Загрузка плагинов без мутации `sys.path` (`spec_from_file_location`) | 2026-03-29 |

---

## 7. Архив решений (подробности)

### Удаление `core/orchestration/`

После переноса в `app/orchestration/` дублирующие файлы в core удалены; `CoreRuntime` не тянет Docker-реализацию на уровне импорта (TYPE_CHECKING / инъекция сервиса).

### Наблюдаемость в core

`print` и `traceback.print_exc` в рабочих путях заменены на логирование; исключение — легитимный fallback до инициализации логгера.

### D1: нормализация обработки исключений в `core/` (2026-04-06)

- Политика: **не использовать** широкие `except Exception` в рабочих путях; допустимы только защитные boundary, где ошибка **логируется** с контекстом и runtime **продолжает работу** (graceful degradation).
- Для ожидаемых классов ошибок на границе выделены allowlist-группы:
  - `core/adapters/storage_errors.py`: `STORAGE_BOUNDARY_ERRORS`
  - `core/exception_groups.py`: `PLUGIN_INTROSPECTION_ERRORS` (единая группа вместо локальных дублей)
- Инварианты:
  - `asyncio.CancelledError` **не глотается** (пробрасывается)
  - неожиданные исключения помечаются как **unexpected** и логируются с `exc_info=True`
- Guard: тест `tests/test_core_exception_policy.py` запрещает `except Exception` / `except:` / `except BaseException` в `core/` и требует корректное обращение с `CancelledError`.
- Метрика: строк с подстрокой `except Exception` в `core/` — **0** (см. §2).

### Инкапсуляция operations

`OperationWorker` переведён на публичные методы `OperationManager` вместо доступа к `_storage` / `_executor`.

### Декомпозиция God Object и шины событий

`CoreRuntime` собирается из компонентов; event bus и plugin lifecycle разбиты на меньшие классы с делегированием (см. реестр B1–B3).

### Плагины: контекст и лоадер

Вместо `setattr` на класс плагина — формализованный контекст и манифест; загрузка модуля по файлу без изменения `sys.path`.

### Capability system (2026-04-02)

Исправлены передача `capability_registry`, порядок аргументов `register_provider`, регистрация consumers и проверки при `start_plugin` (см. тесты capability).

---

*Конец документа.*
