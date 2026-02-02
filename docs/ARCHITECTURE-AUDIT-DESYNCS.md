# Архитектурный аудит: рассинхроны слоёв

> **Тип:** Анализ (read-only). Код не менялся.  
> **Область:** core/, modules/, plugins/, docs/. admin-ui-service в репозитории нет — учтены только контракты core-runtime-service.

---

## Часть 1. Executive Summary

### Ключевые рассинхроны (5–10)

| # | Рассинхрон | Блокирует развитие? | Тип |
|---|------------|----------------------|-----|
| 1 | **HTTP path `/admin/v1/inspector/*` → service `admin.v1.*`** (без префикса inspector в имени сервиса). Единственное исключение: `admin.v1.inspector.operations`. Остальные Inspector-views: `admin.v1.runtime`, `admin.v1.plugins` и т.д. — путь говорит "inspector", имя сервиса — нет. | Косметика | Naming |
| 2 | **GET /admin/v1/integrations** не под префиксом Inspector (`/admin/v1/inspector/`), хотя по смыслу read-only snapshot. Сервис `admin.v1.integrations` регистрируется в IntegrationsModule, путь — вне единого пространства Inspector. | Косметика | Boundary |
| 3 | **oauth.refresh_token** — handler есть в `modules/operations/handlers.py`, но **нигде не регистрируется** (AdminModule перестал регистрировать operations handlers). Операция мёртвая: в списке Inspector не появится, POST /admin/v1/operations с типом `oauth.refresh_token` даст "unknown operation". | **Да** | Lifecycle |
| 4 | **authz.py** содержит scope-маппинг для **admin.devices.***, admin.list_plugins, admin.state_keys** — сервисы в AdminModule больше не регистрируются. Мёртвые записи в ACTION_SCOPE_MAP; validation_models всё ещё ссылается на `admin.devices.set_state`. | Средний (путаница, лишняя логика) | Responsibility |
| 5 | **admin.v1.inspector.operations** отсутствует в ACTION_SCOPE_MAP (authz). Разрешение идёт по fallback `action.startswith("admin.")` → требуется `admin.*`. Работает, но явного контракта нет. | Косметика | Naming |
| 6 | **Сервисы oauth_yandex.***, yandex_device_auth.*** — по документации это capability-провайдеры, но вызываются по имени плагина** (yandex_smart_home использует фасад oauth_provider; без фасада — прямая привязка к имени). | Уже смягчено фасадом | Capability vs Implementation |
| 7 | **presence**: HTTP path `/presence/enter`, service name **`presence.set?home=true`** — параметр в имени сервиса (query в service), не в path. Отличается от остальных контрактов (path → service без query). | Косметика | Naming / Boundary |
| 8 | **adapters/http/admin_routes.py** регистрирует **дубликат** GET /admin/v1/integrations в HttpRegistry и создаёт отдельный FastAPI router. IntegrationsModule тоже регистрирует тот же path. Риск двойной регистрации, если admin_routes подключается к app. | Зависит от использования create_admin_router | Boundary |
| 9 | **Документация**: ADMIN_PANEL_SECURITY.md, 09-APPLICATION-USE-CASE-MODEL.md, 10-DEVELOPMENT-RULES — ссылки на **admin.devices.***, /admin/v1/runtime** (старые пути). Факт: устройства только через operations; Inspector под /admin/v1/inspector/*. | Средний (вводит в заблуждение) | Documentation |
| 10 | **dev-scripts/quasar_ws_smoke.py** вызывает **admin.v1.yandex.sync** — сервис удалён; скрипт сломается. | Да (скрипт) | Lifecycle |

**Блокирующие:** 3 (мёртвый oauth.refresh_token, устаревшие скрипты/документация при использовании).  
**Косметика / средний риск:** остальное.

---

## Часть 2. Классификация рассинхронов

### 2.1 Naming

- **HTTP path vs service name:** пути `/admin/v1/inspector/runtime`, `.../plugins` и т.д., сервисы `admin.v1.runtime`, `admin.v1.plugins` — в имени сервиса нет "inspector", кроме `admin.v1.inspector.operations`.
- **presence:** сервис `presence.set?home=true` — параметр в имени сервиса; остальные контракты — путь + body/path params, без query в service name.

### 2.2 Boundary

- **Integrations:** read-only список интеграций живёт как GET /admin/v1/integrations и сервис `admin.v1.integrations` в IntegrationsModule; по архитектуре это Inspector-view, но путь не под `/admin/v1/inspector/`.
- **admin_routes.py:** дублирует регистрацию /admin/v1/integrations (HttpRegistry + свой router); граница "кто владеет admin read-only" размыта.

### 2.3 Responsibility

- **authz.py:** хранит маппинг для admin.devices.*, admin.list_plugins, admin.state_keys — эти сервисы не регистрируются AdminModule; ответственность "кто что регистрирует" и "кто что проверяет по scope" расходится.
- **validation_models.py:** есть модель для `admin.devices.set_state`; такого сервиса в регистрации нет.

### 2.4 Lifecycle

- **oauth.refresh_token:** handler определён в modules/operations/handlers.py, ни один модуль/плагин не вызывает `ops.register_handler("oauth.refresh_token", ...)`. Операция не появляется в Inspector и не выполняется.

### 2.5 Capability vs Implementation

- **oauth_yandex**, **yandex_device_auth:** в PluginMetadata указаны capabilities_provided; потребитель (yandex_smart_home) идёт через фасад oauth_provider, а не по имени плагина. Прямые вызовы по имени сервиса (oauth_yandex.get_status и т.д.) остаются в authz и в части кода — оформлены как "legacy" в документации, что согласовано.

---

## Часть 3. Таблицы рассинхронов

### 3.1 HTTP ↔ Service

| HTTP Path | Service Name | Роль | Проблема | Рекомендуемое выравнивание |
|-----------|--------------|------|----------|----------------------------|
| GET /admin/v1/inspector/runtime | admin.v1.runtime | Inspector | Путь содержит "inspector", имя сервиса — нет | Либо переименовать сервисы в admin.v1.inspector.runtime и т.д., либо зафиксировать в доке, что "admin.v1.*" = Inspector views |
| GET /admin/v1/inspector/plugins | admin.v1.plugins | Inspector | То же | То же |
| GET /admin/v1/inspector/services | admin.v1.services | Inspector | То же | То же |
| GET /admin/v1/inspector/http | admin.v1.http | Inspector | То же | То же |
| GET /admin/v1/inspector/events | admin.v1.events | Inspector | То же | То же |
| GET /admin/v1/inspector/dashboard | admin.v1.dashboard | Inspector | То же | То же |
| GET /admin/v1/inspector/storage | admin.v1.storage | Inspector | То же | То же |
| GET /admin/v1/inspector/state | admin.v1.state | Inspector | То же | То же |
| GET /admin/v1/inspector/state/keys | admin.v1.state.keys | Inspector | То же | То же |
| GET /admin/v1/inspector/state/{key} | admin.v1.state.get | Inspector | То же | То же |
| GET /admin/v1/inspector/operations | admin.v1.inspector.operations | Inspector | Имя согласовано с путём | — |
| GET /admin/v1/integrations | admin.v1.integrations | Read-only (по смыслу Inspector) | Путь не под /admin/v1/inspector/ | Перенести путь в /admin/v1/inspector/integrations или явно описать в доке исключение |
| POST /admin/v1/operations | admin.operations.create | Operations proxy | Нет рассинхрона | — |
| GET /admin/v1/operations | admin.operations.list | Operations proxy | Нет рассинхрона | — |
| GET/POST /admin/v1/operations/{id}... | admin.operations.get/cancel/retry | Operations proxy | Нет рассинхрона | — |
| POST/GET /admin/v1/auth/* | admin.auth.* | Auth | Нет рассинхрона | — |
| POST /presence/enter | presence.set?home=true | Presence | Параметр в имени сервиса (query) | Выровнять: либо отдельные пути под сервисы с параметром, либо один path + body |

### 3.2 ServiceRegistry ↔ Capability

| Service | Реальная роль | Сейчас оформлено как | Проблема | Что должно быть |
|---------|----------------|----------------------|----------|------------------|
| oauth_yandex.get_status, get_access_token, get_cookies | Capability oauth:yandex | Сервисы плагина oauth_yandex | Вызов по имени плагина; потребитель переведён на фасад | Фасад (есть). Остальные вызовы — legacy, документировать и по возможности убрать |
| yandex_device_auth.get_session, get_cookies | Capability yandex:session_cookies | Сервисы плагина yandex_device_auth | То же | То же |
| yandex.sync_devices, yandex.check_devices_online | Доменные операции плагина | Сервисы + operations в плагине | Нет: плагин сам регистрирует и сервисы, и operations | — |
| admin.v1.integrations | Inspector-view (read-only список) | Сервис в namespace admin.v1, регистрация в IntegrationsModule | Namespace admin.v1 смешан с "Inspector" (часть под inspector, интеграции — нет) | Либо admin.v1.inspector.integrations + путь /admin/v1/inspector/integrations, либо явное исключение в доке |

### 3.3 Operation type ↔ Handler ↔ Домен

| Operation Type | Где регистрируется | Реальный домен | Проблема | Нормализация |
|----------------|--------------------|----------------|----------|--------------|
| device.set_state | DevicesModule.start() → devices/operations.py | devices | Нет | — |
| device.mapping.create/delete/auto | То же | devices | Нет | — |
| yandex.sync_devices | yandex_smart_home on_start() → plugins/.../operations.py | yandex_smart_home | Нет | — |
| yandex.check_devices_online | То же | yandex_smart_home | Нет | — |
| oauth.refresh_token | **Нигде** | OAuth (плагин oauth_yandex) | Handler в modules/operations/handlers.py есть, регистрации нет | Либо oauth_yandex в on_start() регистрирует oauth.refresh_token, либо удалить handler и упоминания из доков |

### 3.4 Namespace

| Namespace | Что туда попало | Почему плохо | Как лучше |
|-----------|-----------------|--------------|-----------|
| admin.v1.* | Inspector views (runtime, plugins, services, http, events, dashboard, storage, state, state.keys, state.get) + один явный inspector (admin.v1.inspector.operations) | Смешение "v1" и "inspector": часть — общий read-only, одна сущность с префиксом inspector | Единообразие: либо все Inspector как admin.v1.inspector.*, либо все admin.v1.* и в доке зафиксировать, что admin.v1 = Inspector |
| admin.v1.integrations | Список интеграций (read-only), регистрируется IntegrationsModule | Тот же namespace admin.v1, но путь не inspector; владелец — другой модуль | Либо admin.v1.inspector.integrations + путь под /inspector/, либо оставить и описать в доке |
| admin.operations.* | create, list, get, cancel, retry — прокси к OperationManager | Нет рассинхрона | — |
| admin.auth.* | Auth-операции | Нет рассинхрона | — |
| admin.devices.* | В коде AdminModule не регистрируются; в authz и validation_models остались | Мёртвый namespace в ACL/validation | Удалить из authz и validation_models или пометить deprecated |
| admin.list_plugins, admin.state_keys, admin.state_get | В authz; в AdminModule таких имён нет (есть admin.v1.plugins и т.д.) | Устаревшие имена | Удалить из authz |

### 3.5 Module / Plugin responsibility drift

| Компонент | Что делает | Что не должен делать | Минимальный шаг |
|-----------|------------|----------------------|------------------|
| AdminModule | Регистрирует Inspector-сервисы (admin.v1.*, admin.v1.inspector.operations), admin.operations.*, admin.auth.*, HTTP endpoints. Регистрирует system.webhook_test. | Регистрировать operations handlers, знать плагины/домены, содержать бизнес-логику | Уже приведён к glue. Убрать регистрацию webhook_test в admin при желании вынести в adapters. |
| IntegrationsModule | Регистрирует сервис admin.v1.integrations и GET /admin/v1/integrations; вызывает admin_v1_integrations из modules/admin/integrations.py. | Владеть "admin" namespace логически — но сервис под admin.v1, это приемлемо при явном договоре | Перенести путь в /admin/v1/inspector/integrations и/или имя в admin.v1.inspector.integrations для единообразия |
| AuthModule | Регистрирует только HTTP → admin.auth.*. Сервисы в AdminModule. | Дублировать регистрацию сервисов | Нет изменений |
| OperationsModule | Регистрирует только HTTP → admin.operations.*. Сервисы в AdminModule. | Регистрировать handlers | Нет изменений; handlers в devices/плагинах |
| modules/operations/handlers.py | Содержит только handle_oauth_refresh. | Регистрировать handler — регистрацию делает кто-то другой; сейчас никто не регистрирует | Либо oauth_yandex при старте регистрирует oauth.refresh_token, либо удалить handler и не обещать операцию в доке |
| adapters/http/admin_routes.py | Создаёт router, регистрирует GET /admin/v1/integrations в HttpRegistry и дублирует вызов сервиса в @router.get. | Дублировать контракт, который уже регистрирует IntegrationsModule | Удалить регистрацию из admin_routes или не подключать create_admin_router, если не используется |
| modules/api/authz.py | ACTION_SCOPE_MAP для admin.devices.*, admin.list_plugins и т.д. | Хранить scope для несуществующих сервисов | Удалить мёртвые записи; добавить admin.v1.inspector.operations в map при желании явного контракта |

### 3.6 Документация ↔ Реальность

| Документ | Утверждение | Реальность | Риск | Нужно обновить |
|----------|-------------|------------|------|-----------------|
| ADMIN_PANEL_SECURITY.md | Примеры с /admin/v1/runtime | Пути теперь /admin/v1/inspector/runtime | Неточные примеры для интеграции/настройки | Да |
| 09-APPLICATION-USE-CASE-MODEL.md | admin.devices.get, регистрация admin.devices.get | Сервисы не регистрируются; устройства — через operations | Ложная модель "read через admin.devices" | Да |
| 10-DEVELOPMENT-RULES | Вызовы admin.devices.get, set_state, list | Таких сервисов нет | Разработчик будет вызывать несуществующие сервисы | Да |
| 01-ARCHITECTURE.md | Inspector paths: /admin/v1/inspector/* | В коде так и есть | Нет | — |
| 01-ARCHITECTURE.md | UI/CLI читают только через Inspector | Реализация такова; скрипты (quasar_ws_smoke) ещё вызывают admin.v1.yandex.sync | Скрипты ломаются | Обновить скрипты; в доке уже верно |
| authz.py (комментарии / код) | admin.devices.*, admin.list_plugins в ACTION_SCOPE_MAP | Сервисы не регистрируются | Путаница при поддержке ACL | Удалить мёртвые записи |
| OPERATIONS_IMPLEMENTATION.md, FORENSIC_ANALYSIS_SERVICES.md | oauth.refresh_token, admin.devices.* зарегистрированы | oauth.refresh_token не регистрируется; admin.devices.* нет | Устаревшие справочники | Обновить или пометить устаревшими |

---

## Часть 4. Топ-10 архитектурных долгов

Отсортировано по влиянию и риску (без изменения Core).

| # | Долг | Влияние | Риск | Стоимость исправления |
|---|------|---------|------|------------------------|
| 1 | **oauth.refresh_token не регистрируется** | Операция недоступна из UI/API | Высокий, если ожидается обновление токенов через operations | Низкая: регистрация в oauth_yandex on_start() или удаление handler |
| 2 | **Скрипты и доки ссылаются на admin.v1.yandex.sync, admin.devices.*** | Сломанные скрипты, неверные гайды | Высокий при использовании старых путей/сервисов | Низкая: обновить пути и примеры |
| 3 | **authz и validation_models содержат admin.devices.*, admin.list_plugins** | Мёртвый код, путаница в ACL | Средний | Низкая: удалить записи |
| 4 | **GET /admin/v1/integrations вне /admin/v1/inspector/** | Несогласованность "всё read-only под inspector" | Низкий | Низкая: перенести путь или зафиксировать исключение в доке |
| 5 | **Дубликат /admin/v1/integrations в admin_routes.py** | Возможная двойная регистрация | Зависит от подключения router | Низкая: убрать дубликат или не использовать admin_routes |
| 6 | **admin.v1.* без "inspector" в имени при path /inspector/*** | Разные соглашения path vs service name | Низкий | Средняя при переименовании всех сервисов |
| 7 | **presence: service name с query (presence.set?home=true)** | Отличие от остальных контрактов | Низкий | Средняя при смене контракта |
| 8 | **admin.v1.inspector.operations не в ACTION_SCOPE_MAP** | Разрешение только по fallback admin.* | Низкий | Низкая: одна строка в map |
| 9 | **Устаревшие FORENSIC_ANALYSIS_SERVICES, OPERATIONS_IMPLEMENTATION** | Неверная карта сервисов/операций | Средний при использовании как референс | Низкая: пометить устаревшим или обновить |
| 10 | **09-APPLICATION-USE-CASE-MODEL: admin.devices как Application Service** | Модель не совпадает с текущей архитектурой (operations + Inspector) | Средний для онбординга | Средняя: переписать разделы под operations + Inspector |

---

## Часть 5. Рекомендованный план фиксации

Без написания кода — только шаги.

### Iteration A — Нейминг и мёртвый код

1. **authz.py:** удалить из ACTION_SCOPE_MAP записи: admin.devices.*, admin.list_plugins, admin.list_services, admin.list_http, admin.state_keys, admin.state_get. Добавить (по желанию) admin.v1.inspector.operations → admin.read.
2. **validation_models.py:** удалить или пометить deprecated маппинг для admin.devices.set_state (если endpoint не используется).
3. **Документация:** в 01-ARCHITECTURE или отдельном глоссарии зафиксировать: "admin.v1.* — сервисы Inspector (read-only); пути GET /admin/v1/inspector/*".

### Iteration B — Границы

4. **Integrations:** перенести путь на GET /admin/v1/inspector/integrations и сервис на admin.v1.inspector.integrations ИЛИ оставить как есть и в доке явно указать исключение "integrations list — read-only, но путь вне /inspector/ по историческим причинам".
5. **admin_routes.py:** если create_admin_router не используется в ApiModule — удалить регистрацию HttpEndpoint и роут для integrations. Если используется — убрать дубликат с IntegrationsModule (один владелец контракта).
6. **presence:** зафиксировать в контракте, что параметр передаётся через service name query (текущее поведение) ИЛИ перейти на один path + body (тогда меняется и HttpRegistry, и обработчик).

### Iteration C — Operations и Inspector

7. **oauth.refresh_token:** либо в plugins/oauth_yandex при on_start() вызвать register_handler("oauth.refresh_token", handler) (handler можно импортировать из modules/operations/handlers или продублировать в плагине), либо удалить handle_oauth_refresh из modules/operations/handlers и все упоминания операции из доков.
8. **Скрипты:** dev-scripts/quasar_ws_smoke.py и др. — заменить вызов admin.v1.yandex.sync на POST /admin/v1/operations с type yandex.sync_devices (и обновить пути на /admin/v1/inspector/* где нужен read-only).

### Iteration D — Документация

9. **ADMIN_PANEL_SECURITY.md:** заменить /admin/v1/runtime на /admin/v1/inspector/runtime в примерах.
10. **09-APPLICATION-USE-CASE-MODEL.md, 10-DEVELOPMENT-RULES:** переписать разделы про admin.devices и "read API" под модель: чтение только через Inspector (GET /admin/v1/inspector/*), мутации через POST /admin/v1/operations.
11. **FORENSIC_ANALYSIS_SERVICES.md, OPERATIONS_IMPLEMENTATION.md:** пометить устаревшими или обновить таблицы сервисов/операций под текущую регистрацию.

---

## Критерий успеха аудита

После отчёта ясно:

- **Где система говорит одно, а делает другое:** доки и authz обещают admin.devices.* и admin.v1.yandex.sync; в коде их нет. Операция oauth.refresh_token описана, но не регистрируется.
- **Какие имена вводят в заблуждение:** admin.v1.* без "inspector" при путях /inspector/*; presence.set?home=true как имя сервиса.
- **Где архитектура зрелая:** AdminModule = glue; Inspector только читает; operations в доменах/плагинах; устройства и Yandex через operations. Зрелость есть, хвосты — в мёртвом коде, нейминге и документации.
- **Как развивать без хаоса:** править по итерациям A→B→C→D; не трогать Core; не вводить новые фреймворки; явно фиксировать в доке контракты (path ↔ service ↔ роль).
