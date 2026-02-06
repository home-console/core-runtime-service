# SDK-DECISION.md

**Дата:** 2026-02-02  
**Цель:** Решить, что делать со старым SDK (python-sdk) относительно нового Plugin SDK (core-runtime-service/sdk, D1).

---

## 1. Что такое старый SDK на самом деле

Старый SDK — пакет **home_console_sdk** в `/python-sdk`. По факту это **не один продукт, а комбайн** из четырёх разных ролей:

| Роль | Содержимое | Реальность |
|------|------------|------------|
| **Внешний плагин (микросервис)** | PluginBase, CoreAPIClient, run(), authenticate() | Клиент к Core API + свой event loop; плагин как отдельный процесс. |
| **Встраиваемый плагин (in-process)** | InternalPluginBase, DatabaseClient, EventsClient, PluginConfig, TaskManager, FastAPI APIRouter, mount_router, db_session_maker, event_bus | Контракт под старую архитектуру: прямой доступ к app, БД, EventBus; монтирование роутов в FastAPI. |
| **Remote plugin (HTTP контракт)** | RemotePluginBase, create_lifecycle_handlers, register_service, get_metadata | Описание контракта удалённого плагина (lifecycle endpoints, сервисы); без реализации runtime. |
| **Client/helpers** | CoreAPIClient, auth, config, db, events, models, exceptions, tasks | HTTP-клиент к Core/Admin API, модели (User, Device, Plugin), исключения, фоновые задачи, конфиг из env. |

**Факт:** В core-runtime-service плагины **не используют** home_console_sdk. Они наследуют `core.base_plugin.BasePlugin`, который наследует **sdk.BasePlugin** (новый SDK D1). Старый SDK нигде в репозитории не импортируется кроме самого пакета python-sdk (README, examples, docstrings).

---

## 2. Что такое новый SDK по контракту

**Новый SDK (D1)** — каталог `core-runtime-service/sdk`. По контракту это **только**:

- **BasePlugin** (ABC): lifecycle on_load / on_start / on_stop / on_unload; свойство `metadata` → PluginMetadata.
- **PluginMetadata** (frozen dataclass): name, version, description, is_integration, integration_flags, capabilities_provided, capabilities_required.
- **PluginRuntime** (Protocol): service_registry, event_bus, storage, state, operations — без типов реализации.
- **CapabilityId** = str: строковый контракт capability.
- **Lifecycle** — только документация (когда что делать), без кода.

**Не содержит:** HTTP, asyncio.run/event loop, Admin API, Product API, client logic, FastAPI, SQLAlchemy, реализацию runtime.

**Одним предложением:**  
**Новый SDK — это контракт плагина (BasePlugin + PluginMetadata + PluginRuntime + capabilities и lifecycle), без реализации runtime и без клиентского/админского API.**

---

## 3. Где они конфликтуют

| Концепт | Старый SDK | Новый SDK | Конфликт |
|---------|------------|-----------|----------|
| **BasePlugin** | PluginBase (внешний) + InternalPluginBase (встраиваемый); оба с helpers, HTTP/DB/events | Один BasePlugin, только lifecycle + metadata, без HTTP/DB | ⚠️ Разные контракты: старый = «я приложение/часть приложения», новый = «я расширение, меня вызывает Core». |
| **Runtime** | Конкретный: app, db_session_maker, event_bus, CoreAPIClient, get_current_user и т.д. | Protocol: service_registry, event_bus, storage, state, operations | ❌ Несовместимо: старый ожидает FastAPI/SQLAlchemy, новый — opaque Protocol. |
| **HTTP client** | CoreAPIClient (login, devices, plugins, admin) | Нет | ❌ Только в старом. |
| **Admin / Product API** | В клиенте (get_list_plugins, get_stats, list_devices и т.д.) | Нет | ❌ Только в старом. |
| **Capabilities** | Нет (только dependencies по имени плагина) | Есть (capabilities_provided/required, string-based) | ❌ Только в новом. |
| **Lifecycle** | Implicit (on_start/on_stop + run() у внешнего; on_load/on_unload + mount_router у внутреннего) | Explicit (только on_load→on_start→on_stop→on_unload, только Core вызывает) | ⚠️ Разная семантика и кто владелец lifecycle. |
| **Config** | PluginConfig из env, get_config() в базе | Нет в SDK (плагин получает всё через runtime/storage) | ❌ Старый тянет env-конфиг в контракт. |
| **Remote plugin** | RemotePluginBase + create_lifecycle_handlers (HTTP контракт) | Нет (remote — отдельный контракт Core) | ⚠️ Старый даёт «полу-SDK» для remote; новый его не дублирует. |

**Вывод:** старый SDK ≠ Plugin SDK. Это комбайн: client + старый in-process/remote контракт + helpers. С новым SDK совместим только по идее «есть какой-то базовый класс и lifecycle», но не по типу runtime и не по границам (HTTP, admin, DB).

---

## 4. Что из старого SDK: удалить / вынести / мигрировать / заморозить

Инвентаризация по файлам (факты + решение).

### Шаг 1. Инвентаризация старого SDK (факты)

| Файл | Импорты | Что делает | Тип |
|------|--------|------------|-----|
| `__init__.py` | Re-export всего пакета | Публичный API: PluginBase, InternalPluginBase, RemotePluginBase, CoreAPIClient, DatabaseClient, EventsClient, PluginConfig, TaskManager, auth, models, exceptions | — |
| `plugin.py` | httpx — нет; fastapi APIRouter, Request; .client, .db, .events, .config, .tasks; logging, os, json, pathlib | PluginBase: CoreAPIClient, run(), authenticate(), on_start/on_stop, get_config; InternalPluginBase: app, db_session_maker, event_bus, mount_router, EventsClient, DatabaseClient, PluginConfig, TaskManager, _get_current_user_id, load_manifest | PLUGIN_CONTRACT (старый) + RUNTIME_IMPL |
| `client.py` | httpx; .models, .exceptions | CoreAPIClient: login, register, get_current_user, list_devices, get_device, create_device, update_device, delete_device, get_plugin, get_list_plugins, call_plugin, get_stats; Bearer auth | CLIENT_SDK |
| `auth.py` | fastapi HTTPException, Header, Depends, HTTPBearer | PluginAuth, require_api_key, require_bearer_token (FastAPI Depends) | CLIENT_SDK / HELPERS |
| `config.py` | pydantic, os, json | PluginConfig: get из env с префиксом PLUGIN_{id}, cast, get_int/bool/float/list/dict, load_from_model | HELPERS |
| `db.py` | sqlalchemy (AsyncSession, async_sessionmaker, text, Table, MetaData) | DatabaseClient: get_session, query, execute, register_model, _validate_table_access (префикс таблиц плагина) | RUNTIME_IMPL |
| `events.py` | — | EventsClient: emit, subscribe, on (декоратор), unsubscribe; обёртка над event_bus с префиксом plugin_id | RUNTIME_IMPL |
| `models.py` | pydantic | User, Device, DeviceCreate, DeviceUpdate, Plugin — DTO для API | CLIENT_SDK |
| `exceptions.py` | — | HomeConsoleSDKError, AuthenticationError, APIError, NotFoundError, ValidationError | HELPERS / CLIENT_SDK |
| `tasks.py` | asyncio, logging, datetime, functools | TaskManager, BackgroundTask, background_task, schedule — фоновые задачи для плагина | RUNTIME_IMPL / HELPERS |
| `remote_plugin.py` | abc, typing, datetime, json | RemotePluginBase: on_load/on_start/on_stop/on_unload, health, register_service, get_metadata, validate_metadata; create_lifecycle_handlers → dict handlers для FastAPI | PLUGIN_CONTRACT (remote) |
| `_version.py` | — | __version__ = "0.0.2" | — |

### Шаг 2. Инвентаризация нового SDK (D1)

- Содержит: BasePlugin, PluginMetadata, PluginRuntime (Protocol), CapabilityId (str), lifecycle (документация).
- Не содержит: HTTP, asyncio runtime, admin/ui/product API, client logic.

**Формулировка:**  
«Новый SDK — это контракт плагина (BasePlugin + PluginMetadata + PluginRuntime + capabilities и lifecycle), без реализации runtime и без клиентского/админского API.»

### Шаг 3. Классификация старого SDK по судьбе

| Файл / блок | Решение | Обоснование |
|-------------|--------|-------------|
| **plugin.py** (PluginBase, InternalPluginBase) | ❌ **DELETE** (или 🧊 FREEZE как legacy) | Контракт in-process/внешний плагина не совместим с D1; Core уже использует sdk.BasePlugin через core.base_plugin. Не мигрировать в новый SDK — там другой контракт. |
| **remote_plugin.py** | 🧊 **FREEZE** (или 📦 EXTRACT в отдельный пакет «remote plugin contract») | Описывает HTTP-контракт удалённого плагина; Core уже имеет 05-REMOTE-PLUGIN-CONTRACT.md и реализацию proxy. Можно оставить как deprecated helper для тех, кто пишет remote плагины на Python, но не тянуть в новый SDK. |
| **client.py** | 📦 **EXTRACT → client SDK** | Чистый HTTP-клиент к Core/Admin API. Вынести в отдельный пакет (например homeconsole-client или homeconsole-admin-client). |
| **auth.py** | 📦 **EXTRACT → client SDK** (или в пакет с FastAPI helpers) | require_api_key, require_bearer_token — для приложений, вызывающих API; логически с client. |
| **config.py** | 🔁 **MIGRATE** опционально / 📦 EXTRACT | Общая идея «конфиг из env по префиксу» может жить в client/CLI пакете; в Plugin SDK D1 конфига нет (только runtime/storage). Не переносить в sdk. |
| **db.py** | ❌ **DELETE** | Специфично под старую архитектуру (SQLAlchemy, session_maker, таблицы с префиксом плагина). В D1 плагин не имеет прямого доступа к БД — только storage/state через runtime. |
| **events.py** | ❌ **DELETE** (реализация в Core) | Обёртка над event_bus уже есть в Core; плагин вызывает runtime.event_bus. Не дублировать в SDK. |
| **models.py** | 📦 **EXTRACT → client SDK** | User, Device, DeviceCreate, DeviceUpdate, Plugin — DTO для клиента API. |
| **exceptions.py** | 📦 **EXTRACT → client SDK** (или общий пакет errors) | APIError, NotFoundError и т.д. нужны клиенту; в Plugin SDK не входят. |
| **tasks.py** | ❌ **DELETE** (или 🧊 FREEZE) | Фоновые задачи — ответственность плагина и Core (планировщик); в D1 нет своего TaskManager. Не переносить в новый SDK. |
| **_version.py** | — | Оставить в пакете, где будет судьба (client / freeze). |

**Итог по судьбе:**

- ❌ **DELETE:** plugin.py (PluginBase, InternalPluginBase), db.py, events.py; при варианте «распил» — и весь пакет как «plugin SDK» удалить, оставив только вынесенный client.
- 📦 **EXTRACT → client SDK:** client.py, auth.py, models.py, exceptions.py; опционально config.py.
- 🔁 **MIGRATE:** Ничего в новый SDK не мигрировать (контракт другой; новый уже есть в sdk/).
- 🧊 **FREEZE:** remote_plugin.py (и при желании весь старый пакет) — deprecated, read-only, для legacy пользователей; либо вынести RemotePluginBase в отдельный маленький пакет «remote plugin contract».

---

## 5. Итоговая стратегия (два варианта)

### Вариант A (рекомендуемый): Старый SDK = legacy client; новый SDK = единственный Plugin SDK

- **Старый SDK (python-sdk):**
  - Объявить **deprecated** и **заморозить** в текущем виде.
  - В README явно указать: «Plugin SDK для новых плагинов — core-runtime-service/sdk (и контракт 08-PLUGIN-CONTRACT.md). Данный пакет сохраняется только для существующих пользователей HTTP/Admin клиента и remote plugin helpers.»
  - Не удалять код сразу: **FREEZE** (без новых фич, только критические фиксы безопасности при необходимости).
- **Новый SDK (sdk/):**
  - Единственный официальный Plugin SDK для Stage D.
  - Версионировать отдельно (например 0.x / 1.0), документировать в 08-PLUGIN-CONTRACT.md и sdk/README.md.
- **Плюсы:** Один контракт плагина; нет смешивания client и plugin; Stage D перестаёт быть «скользким».  
- **Минусы:** Пользователи старого пакета должны со временем перейти на client-пакет (если его вынести) или оставаться на замороженной версии.

### Вариант B: Распилить старый SDK; новый SDK — основной

- **Вынести в отдельный пакет (например homeconsole-client):**  
  client.py, auth.py, models.py, exceptions.py, при желании config.py.  
  Имя: например `homeconsole-client` или `homeconsole-admin-client`.  
  Назначение: HTTP-клиент к Core/Admin/Product API для приложений (в т.ч. скрипты, админки).
- **Удалить из старого пакета (или весь пакет переименовать в client):**  
  plugin.py (PluginBase, InternalPluginBase), db.py, events.py, tasks.py.  
  Не переносить в новый SDK.
- **Remote plugin:**  
  Либо оставить remote_plugin.py в старом пакете как deprecated, либо вынести в маленький пакет «homeconsole-remote-plugin» (только RemotePluginBase + create_lifecycle_handlers).
- **Новый SDK:**  
  Как в варианте A — единственный Plugin SDK для плагинов в Core.
- **Плюсы:** Чёткое разделение: client vs plugin SDK; старый «комбайн» исчезает.  
- **Минусы:** Нужен шаг «вынести пакет» и миграция пользователей client-кода.

**Рекомендация:** Вариант A быстрее и достаточно ясен для Stage D; Вариант B — если планируется активное использование HTTP/Admin клиента и хочется отдельный клиентский пакет с нуля.

---

## Контрольные вопросы (ответы ДА/НЕТ)

| Вопрос | Ответ |
|--------|--------|
| 1. Можно ли удалить /python-sdk и Stage D не пострадает? | **ДА.** Плагины Core наследуют core.base_plugin.BasePlugin (sdk.BasePlugin); home_console_sdk в core-runtime-service не используется. |
| 2. Можно ли выпустить новый SDK как v1.0 без оглядки на старый? | **ДА.** Новый SDK уже используется через core.base_plugin; контракт описан в sdk/ и 08-PLUGIN-CONTRACT.md. Старый — отдельный комбайн. |
| 3. Есть ли хоть один файл в старом SDK, который соответствует D1? | **НЕТ.** В старом есть «базовые классы» и lifecycle по названию, но runtime = FastAPI/DB/Client, нет PluginRuntime (Protocol), нет capabilities; контракт другой. |
| 4. Нужно ли внешним плагин-разработчикам старое SDK? | **НЕТ.** Внешние плагины должны писать под контракт D1 (sdk + 08-PLUGIN-CONTRACT.md). Remote-плагины могут опираться на контракт из 05-REMOTE-PLUGIN-CONTRACT.md; старый RemotePluginBase — лишь возможный helper, не обязательный. |
| 5. Можно ли объяснить разницу между SDK за 1 абзац? | **ДА.** Старый SDK — это комбайн: HTTP/Admin клиент, старый контракт in-process/внешнего плагина (FastAPI, БД, EventBus) и helpers для remote. Новый SDK — только контракт плагина: BasePlugin, PluginMetadata, PluginRuntime (Protocol), capabilities и lifecycle; без HTTP, без runtime-реализации, без client. Плагины Core пишут под новый SDK; старый пакет — legacy client / deprecated. |

---

## Итог

- **Старый SDK** — не Plugin SDK, а комбайн (client + старый plugin/remote контракт + helpers).
- **Новый SDK (D1)** — единственный правильный контракт плагина для Stage D.
- **Что делать со старым:** удалить plugin/db/events/tasks из использования как «plugin SDK»; client/auth/models/exceptions — вынести в client-пакет (Вариант B) или оставить пакет замороженным как legacy (Вариант A); remote_plugin — заморозить или вынести в отдельный маленький пакет.
- **Имя и судьба:**  
  - Plugin SDK: `core-runtime-service/sdk` (и контракт в 08-PLUGIN-CONTRACT.md); версионировать и документировать как единственный.  
  - Старый пакет: `home_console_sdk` (python-sdk) — deprecated, freeze; при варианте B — распил на `homeconsole-client` и опционально `homeconsole-remote-plugin`.

После этого шага Stage D перестаёт быть «скользким», SDK становится одним продуктом (контракт плагина), а не мусорным ящиком; можно версионировать SDK, писать документацию, открывать плагины наружу и думать про Rust/Go kernel.

---

## D2. Automation / Flows = домен-оркестратор (не Core, не SDK, не UI)

**Фиксация (2026-02-06):** Automation / Flows трактуем как **чистый доменный оркестратор**, который:

- ❌ **не является частью Core**
- ❌ **не является частью Plugin SDK**
- ❌ **не зависит от Admin UI**
- ✅ использует **ТОЛЬКО EventBus + Operations** (и свои storage/state при необходимости)
- ✅ готов к исполнению в **любом execution режиме** (in-process / process / container), потому что automation не знает, *как* и *где* исполняются операции

**D2 = Automation как домен, а не как фича ядра.**

### Definition of Done (D2) — ответы

| Вопрос | Ответ |
| --- | --- |
| Core Runtime знает, что такое automation | **НЕТ** (automation подключается только через bootstrap списка модулей) |
| Automation можно удалить — Core продолжит работать | **ДА** (в bootstrap automation — OPTIONAL) |
| Automation вызывает доменные сервисы напрямую | **НЕТ** (automation создаёт operations и подписывается на события) |
| Automation создаёт ТОЛЬКО operations | **ДА** |
| UI участвует в логике automation | **НЕТ** |
| Plugin SDK содержит automation-хуки | **НЕТ** |
| Automation знает, где и как исполняется операция | **НЕТ** |

### Кодовая фиксация (high-signal)

- `app/bootstrap.py`: `automation` помечен как **OPTIONAL** (удаляемый модуль)
- `modules/automation/*`: нет вызовов `runtime.service_registry.call(...)`; реакция на события → **создание operation** `automation.run`
- `core/runtime_module.py`: контракт `RuntimeModule` не считает automation “обязательным доменом” по определению

---

## D3. Plugin Execution Layer (in-process / process / container)

**Цель:** добавить *подключаемый* слой исполнения операций (policy + backend), который позволяет
исполнять **одни и те же operations** в разных execution режимах без изменения:
Core, Automation, Plugin SDK, UI.

### Архитектурная модель (D3)

Operation  
↓  
OperationExecutor (Operations subsystem)  
↓  
ExecutionController (policy + backend registry)  
↓  
ExecutionBackend (in_process / process / container)

### Что сделано в коде (минимальный D3-каркас)

- `execution/`:
  - `controller.py`: `ExecutionControllerImpl` — принимает только operation metadata и делегирует в backend по policy
  - `policy.py`: `StateExecutionPolicy` — policy хранится **в storage** и читается на каждый `execute()` (можно менять без рестарта)
  - `backend.py`: `InProcessBackend` (in-process), `ProcessBackend` (local subprocess runner), `ContainerBackend` (docker runner)
  - `backends/process.py`: `ProcessBackend` — запускает общий runner как `python -m execution.runner.homeconsole_runner` (тот же протокол, что и container)
  - `backends/container.py`: `ContainerBackend` — запускает тот же runner через `docker run ...`
  - `runner/`: `ExecutionAdapter` и `homeconsole_runner` — единая execution-среда, не знающая Core/Automation/Plugins/Admin/UI; протокол описан в `docs/EXECUTION-PROTOCOL.md`
- `modules/execution/`:
  - `ExecutionModule` — подключается через bootstrap приложения и делает единственную интеграцию:
    перехватывает `runtime.operations.execute()` и делегирует в `execution_controller`.
- `app/bootstrap.py`: добавлен `ModuleSpec("execution", required=True)` — Execution управляется приложением, не Core.

### Где живёт policy (D3)

Policy хранится как декларативные данные в storage:

- namespace: `execution`
- key: `policy`

Пример:

```yaml
default: in_process
plugins:
  yandex_smart_home: container
operations:
  automation.run: process
```

### Контрольные вопросы D3 (статус)

| Вопрос | Ответ |
| --- | --- |
| 1) Тот же plugin можно запустить в контейнере без изменения кода | **ДА (контрактно)** — backend слой отделён; реализация контейнера будет добавлена без изменений plugin кода |
| 2) Можно поменять execution mode через config без рестарта Core | **ДА** — policy читается из storage на каждый execute |
| 3) Знает ли Core, что такое docker/process/container | **НЕТ** — всё в `execution/`, Core не импортирует docker/subprocess |
| 4) Знает ли automation, где исполняется операция | **НЕТ** |
| 5) Можно добавить новый backend (например WASM) без изменения Operations | **ДА** — достаточно добавить backend и policy |
