# Архитектурные проблемы: Modules & Plugins (актуальный список)

Дата: 2026-04-02 (обновлено)
Объект: `modules/` + `plugins/` (и их граница с `core/`)

Этот файл — **живой backlog** архитектурных проблем именно на стыке module/plugin слоя:
- кто владеет namespace'ами (`admin.*`, `client_manager.*`, `devices.*`)
- кто имеет право регистрировать HTTP/WS/operations
- как устроены contract'ы services/events/operations между слоями

> История закрытых пунктов (A1..F3) намеренно **сжата**: теперь важнее видеть реальные оставшиеся риски.

---

## 1. Ментальная модель: чем модуль отличается от плагина

- **Модуль** (`modules/*`) — часть runtime-композиции (выбирается app-layer через `ModuleSpec`), lifecycle управляет `ModuleManager`.
- **Плагин** (`plugins/*`) — расширение по manifest (`plugin.json`), lifecycle управляет `PluginManager`, может быть изолирован (service/storage proxies), может быть container-mode.
- **Контракт доступа**:
  - модули должны работать через `RuntimeContext`/`context.services`/`context.http`/`context.operations`
  - плагины должны работать через plugin-фасад/прокси и не предполагать "внутренности" ядра

---

## 2. Что уже закрыто (коротко)

✅ Закрыто в этом прогоне и ранее:
- **D3 (AdminModule: десятки inline closure для маппинга параметров)** — закрыто: маппинг вынесен в **`modules/admin/handler_factory.py`** (`normalize_param`, `make_runtime_handler`, `make_runtime_handler_positional`, прокси к `ServiceRegistry`), список регистраций — в **`modules/admin/service_registrations.py`** (`build_admin_registrations`). `modules/admin/module.py` остаётся тонким сборщиком (webhook demo + каталог marketplace + вызов `build_admin_registrations`).
- **D1 (god object admin)** — закрыто: `modules/admin/module.py` стал тонким сборщиком без inline “клея”; вспомогательные handlers вынесены (например `modules/admin/local_services.py`), скрытая инъекция `context.runtime` удалена.
- `runtime.kernel_context` убран из `modules/`
- payload-схемы событий документированы в `core/events_schemas.py` (включая client-manager события)
- унифицированы helper'ы регистрации сервисов в `RuntimeModule`
- plugin dependencies (ERROR-state warning) улучшены
- client-manager namespace ownership исправлен (`client_manager.*` вместо `admin.v1.*`)

---

## 3. Оставшиеся проблемы (крупные)

### At-least-once и единый dedup-контракт (operations + `operation_ready`) ✅ ЗАКРЫТО (G1)
- **Контракт в коде**: `core/operations/dedup_contract.py` (namespace, ключи, TTL, `OPERATION_READY_EVENT_TYPE`); `DedupLayer` и издатели события используют только его.
- **Документация**: `docs/adr/001-dedup-at-least-once-contract.md`, `docs/event_contracts/operation_ready.md`; TypedDict в `core/events_schemas.py` (`OperationReadyPayload`).
- **Регрессия формата ключей**: `tests/test_dedup_contract.py`.
- **Поведение worker** (без изменения смысла):
  - `execute_operation_now`: skip если `processed_op:*`; после терминального persist — `mark_operation_processed`
  - `_on_event` для `operation_ready`: dedup/claim по `payload["id"]` (если есть) + `mark_event_processed` после успеха
- **Тесты worker**: `tests/test_operation_worker.py` (`test_worker_skips_operation_if_already_processed_by_dedup` и др.).

---

### Архитектурный долг, который будет распухать

**Global/singleton state (метрики/лимиты/контекст) ломает изоляцию module↔plugin**
- **Суть**: глобальные "по процессу" штуки неизбежно протекают между:
  - тестами
  - несколькими runtime в одном процессе (если такое появится)
  - плагинами и модулями (в части метрик/лимитов)
- **Риск**: flaky тесты, скрытые зависимости, неочевидное поведение по окружениям.
- **Действие**:
  - плановая миграция с global-accessors на явный DI (через `CoreRuntime`/`RuntimeContext`)
  - оставить backward-compat только как thin wrapper
- **Evidence**:
  - `core/observability/metrics.py` — глобальный back-compat accessor: `_DEFAULT_REGISTRY` + `get_metrics_registry()` создаёт/возвращает singleton.
  - `core/observability/rate_limiter.py` — глобальный singleton: `_rate_limiter: PluginRateLimiter = PluginRateLimiter()`.
  - `core/runtime/operation_context.py` — module-level `_provider` и `_logger` (глобальный provider для `get_operation_id()`/operation logging).
 - **Статус**: ✅ core/modules переведены на per-runtime DI через `RuntimeContext` (`context.metrics`, `context.rate_limiter`, `context.operation_context`). Module-level `get_*()` оставлены только как legacy wrapper.

**Plugin isolation policy не формализована как contract** ✅ ИСПРАВЛЕНО
- **Суть**: есть `ServiceProxy`/`StorageProxy`/`DEFAULT_ALLOWED_SERVICES`, но нет явного "policy spec":
  - какой плагин может вызывать какие сервисы
  - как описывать разрешения в manifest
  - как это отражать в inspector/diagnostics
- **Риск**: security drift (плагины получают больше прав "по умолчанию"), сложность сопровождения.
- **Действие**:
  - добавить декларативные permissions в manifest (services/storage namespaces)
  - валидировать при load/start и показывать в inspector
- **Evidence**:
  - `core/kernel/plugin_sandbox.py` — allowed_services для `ServiceProxy` вычисляются из `getattr(plugin, "_manifest_allowed_services", None)`; если атрибута нет — берётся `runtime.plugin_default_allowed_services`.
  - После фикса: `core/kernel/plugin_sandbox.py` мостит `plugin._plugin_context.manifest.allowed_services` → allowed services для `ServiceProxy`.
  - `tests/test_plugin_allowed_services.py` — добавлен тест, который валидирует: disallowed service вызывает `ForbiddenError`, а allowed service проходит.

**Ошибки и контракты ответов (exception vs `{ok:false}`) на границе HTTP↔service** ✅ ИСПРАВЛЕНО
- **Суть**: внутри доменных сервисов местами "исключения", местами "ok/error dict".
- **Риск**: клиенты (HTTP/API/WS) получают непредсказуемые форматы; плагины копируют поведение как попало.
- **Действие**:
  - выбрать 1 канонический контракт на уровне service boundary (например Result-типы или исключения + middleware нормализация)
  - запретить "смешивание" в новых точках
- **Evidence**:
  - `modules/api/route_binding.py` — добавлены `_normalize_api_result()` и `_normalize_api_error()`: успешный service-result теперь нормализуется в `{ok: True, result: ...}`, а service-exceptions в единый формат `{ok: False, error: ...}` с выставлением `response.status_code`.
  - `tests/test_api_response_contract.py` — unit-тест на canonical contract нормализации.

---

### Качество/портируемость/поддерживаемость

**Hot reload плагинов (importlib.reload) как источник полуживых состояний**
- **Суть**: hot-reload в Python крайне хрупок (двойные типы, утечки подписок, старые ссылки).
- **Риск**: "неповторяемые" баги после reload, утечки памяти/handlers.
- **Действие**:
  - ограничить reload до unload+fresh load (или вынести reload в отдельный процесс/контейнер)
  - формализовать cleanup hooks для плагинов
- **Evidence**:
  - `core/kernel/plugin_lifecycle.py` — вызов `importlib.reload(...)` удалён: reload теперь lifecycle-only (unload→load→start) без "перезамешивания" старого модуля.

**Module discovery по naming convention**
- **Суть**: импорт модулей по имени + implicit class naming.
- **Риск**: слабая диагностика, хрупкость при рефакторинге.
- **Действие**:
  - добавить явный entrypoint/metadata для module (аналог plugin.json)
  - улучшить ошибки discovery (что искали, где, почему не нашли)
- **Evidence**:
  - `core/module_discovery.py` — discovery поддерживает `__runtime_module_class__`, иначе ищет единственный `RuntimeModule` subclass в импортированном модуле; fallback на camelCase остаётся только для совместимости.
  - `tests/test_module_discovery.py` — тесты на discovery без naming convention + ошибка при неоднозначности.

**EventBus API неоднороден (подписки/адаптеры/эвристики)**
- **Суть**: разные сигнатуры/режимы подписки и эвристики определения backend.
- **Риск**: сложность интеграций, расхождение ожиданий между modules и plugins.
- **Действие**:
  - закрепить "канонический" API subscribe/publish + строгие типы payload
  - убрать строковые эвристики backend detection
- **Статус**: payload homogenization ✅, claim-backend detection ✅ (feature-detection по `run_atomic` / `_get_pool`)
- **Evidence**:
  - `core/messaging.py` — payload теперь гомогенизирован: `publish()` добавляет `payload_with_meta["type"] = event_type`, а adapter для simple handler делает `payload.setdefault("type", _event_type)`. Это выравнивает contract между typed и simple handler'ами.
  - `tests/test_event_bus.py` — добавлены проверки, что и typed, и simple handler получают `payload["type"]` и `id`.
  - `core/messaging_claim_manager.py` — backend selection для claim больше не зависит от имени класса/строк: используется feature-detection (`run_atomic` / `_get_pool`), иначе fallback.
  - `tests/test_event_claim_manager.py` — тесты на выбор ветки (sqlite/postgres/fallback).

---

## 4. Рекомендуемая программа исправления (в духе маленьких PR)

Ранее здесь были **PR-1…PR-3** (dedup, manifest permissions, HTTP↔service контракт) — по §3 они **уже закрыты** в коде; этот раздел обновлён под оставшийся хвост.

**Актуальные направления (по убыванию «смысла на объём PR»):**

- **D1 / admin**: дожать «god object» — точечно выносить оставшийся glue из `modules/admin/` без расползания `register` closure.
- **Admin SSH terminal coverage**: `admin_credentials_terminal_ws` и `admin_credentials_terminal_session_close` уже покрыты тестами в [tests/test_admin_credentials_terminal.py](tests/test_admin_credentials_terminal.py).
- **Admin SSH terminal reliability**: `_broadcast()` в [modules/admin/services/ssh_terminal.py](modules/admin/services/ssh_terminal.py) сужен до ожидаемых ошибок event loop/queue dispatch и покрыт тестом.
- **Admin SSH cleanup reliability**: `_SshSession.close()` в [modules/admin/services/ssh_terminal.py](modules/admin/services/ssh_terminal.py) теперь глотает только `OSError` и покрыт тестом.
- **Плагины как артефакты**: supply chain для образов (например `home-console-sdk` / приватный index в Docker CI), при необходимости — job в **корневом** `.github/workflows` с `context: plugins/client-manager-plugin` (вложенный `.github` подкаталога монорепа GitHub не использует).
- **Надёжность**: аудит широких `except Exception` в hot-path — топ-файлы, не весь репозиторий за раз.
- **Структура core (опционально)**: осмысленные пакеты `core/messaging/`, `core/module/` вместо плоских `.py` в корне `core/` — только с явным публичным API и реэкспортом.

Проверка здоровья: **`pytest`** (целевой зелёный прогон), **`scripts/validate_architecture_rules.py`** (AST по дереву).
