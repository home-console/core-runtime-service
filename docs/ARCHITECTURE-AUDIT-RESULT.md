# Архитектурный аудит: результат сквозной проверки

**Дата:** 2026-02-02  
**Режим:** только анализ кода, факты с привязкой к файлу/строке/вызову.

---

## 1. ✅ Confirmed invariants

| Инвариант | Файл / место | Подтверждение |
|-----------|---------------|----------------|
| Core operations.py — только регистрация/диспетчеризация | `core/operations.py` | `register_handler`, `list_handler_types`, `create`, `get`, `list`, `execute` — нет вызовов доменных сервисов, только `storage.set/get/list_keys` и вызов handler по типу (строки 169–281). |
| CapabilityRegistry — только метаданные | `core/capability_registry.py` | Только `register_provider`, `register_consumer`, `unregister_plugin`, `get_providers`, `get_required_capabilities`, `validate_plugin_requirements`. Нет call/resolve/invoke (строки 34–78). |
| Operations регистрируются в плагинах/модулях, не в admin | `plugins/oauth_yandex/plugin.py:882`, `plugins/yandex_smart_home/operations.py:50-51`, `modules/devices/operations.py:106-109` | `register_handler` вызывается только в oauth_yandex on_start, yandex_smart_home (operations.py), devices/operations.py (DevicesModule). В `modules/admin/module.py` вызовов `register_handler` нет. |
| Inspector list_operations_available — только list_handler_types | `modules/admin/services/introspection.py:218-227` | `ops.list_handler_types()`; нет `service_registry.call`, нет доменных имён в логике. |
| AdminModule не регистрирует operation handlers | `modules/admin/module.py` | По всему файлу: нет вызовов `runtime.operations.register_handler`. |
| Product API — только доменные сервисы, /api/v1/* | `modules/product_api/module.py` | Сервисы вызывают только `devices.list`, `devices.get` (строки 36, 40). Пути только `/api/v1/devices`, `/api/v1/devices/{id}`. Нет Inspector, нет operations. |
| Product API optional | `core/module_manager.py:62` | `ModuleSpec("product_api", required=False)`. |
| Admin UI READ — inspector.ts только /admin/v1/inspector/* | `admin-ui-service/src/api/inspector.ts:24` | `const P = '/admin/v1/inspector'`; все get-вызовы от `P`. |
| Admin UI ACTION — operations.ts только /admin/v1/operations | `admin-ui-service/src/api/operations.ts:34,42,46,50,54` | createOperation/list/get/cancel/retry — пути `/admin/v1/operations`. |
| yandex_smart_home вызовы к oauth_yandex / yandex_device_auth только через фасад | `plugins/yandex_smart_home/oauth_provider.py` | Все вызовы `oauth_yandex.*` и `yandex_device_auth.get_session` — только в этом файле (строки 23, 32, 45, 56). Остальной код плагина использует devices.*, yandex.sync_devices (собственные), logger. |

---

## 2. ⚠️ Transitional leftovers

| Что | Файл:строка | Объяснение | Критичность |
|-----|-------------|------------|--------------|
| AdminModule регистрирует POST /admin/v1/devices/{id}/state и сервис admin.v1.devices.set_state | `modules/admin/module.py:190-239` | Мутация вне Operations: прямой вызов `service_registry.call("devices.set_state", ...)`. Legacy-путь для совместимости. | P2 |
| Inspector get_inventory вызывает service_registry.call | `modules/admin/services/introspection.py:238,244,253` | Вызовы `admin.v1.devices.list`, `admin.v1.devices.list_mappings`, `admin.v1.devices.list_external`. Документированное исключение: Control Plane собирает snapshot из своих read-only сервисов. | P3 |
| Admin UI вызывает /oauth/yandex/* и /yandex/auth/device/* | `admin-ui-service/src/api/oauth.ts`, `admin-ui-service/src/hooks/useYandexDeviceAuth.ts`, `admin-ui-service/src/components/YandexDeviceAuthDialog.tsx` | OAuth/Session конфигурация и device auth — не через Inspector/Operations. Исключение для flow конфигурации. | P2 |
| Admin UI хардкодит типы операций в createOperation | `admin-ui-service/src/pages/DevicesPage.tsx:253,286`, `MappingPage.tsx:69`, и т.д. | Типы `yandex.sync_devices`, `yandex.check_devices_online`, `device.set_state`, `device.mapping.*` заданы в коде, а не только из getOperationsAvailable(). Кнопки Sync/Check Online/Set state/Mapping строятся с известными типами. | P3 |
| AdminModule регистрирует GET /admin/v1/devices* (read-only) | `modules/admin/module.py:191-214` | Legacy read-пути вне префикса /admin/v1/inspector/. Дублируют данные, доступные через Inspector inventory. | P3 |

---

## 3. ❌ Violations

| Нарушение | Файл:строка | Объяснение | Критичность |
|-----------|-------------|------------|--------------|
| Core импортирует modules | `core/utils/operation.py:11` | `from modules.request_logger.middleware import get_operation_id, set_operation_id`. Core не должен зависеть от modules. | P1 |
| Inspector знает доменное имя в коде | `modules/admin/services/introspection.py:261-264` | `_inventory_external_providers()` возвращает `["yandex"]` — явное имя провайдера. Документ: «Inspector не знает доменных имён». | P2 |
| Core plugin_manager содержит доменную логику по "oauth" | `core/plugin_manager.py:715-721` | Флаги интеграции: проверка `"oauth" in name_lower or "oauth" in desc_lower` и `"oauth" in dep.lower()`. Доменный термин в core. | P2 |

---

## 4. 🧨 Hidden risks (потенциально опасно)

| Риск | Где | Почему |
|------|-----|--------|
| Удаление admin.v1.devices.* сломает get_inventory | `modules/admin/services/introspection.py:238-253` | get_inventory дергает admin.v1.devices.list/list_mappings/list_external. Если убрать эти сервисы из AdminModule, Inspector inventory перестанет работать. |
| request_logger обязателен для core/utils/operation.py | `core/utils/operation.py:11` | При отключении request_logger импорт core.utils.operation упадёт. |
| OAuth/device auth UI не переведены на Inspector/Operations | admin-ui-service oauth.ts, useYandexDeviceAuth, YandexDeviceAuthDialog | При удалении плагинов oauth_yandex / yandex_device_auth экраны OAuth/Session останутся, но запросы к /oauth/yandex/* и /yandex/auth/device/* дадут 404. |

---

## 5. 🎯 Readiness for Stage D

**Вердикт: YES с условиями.**

- Границы Admin / Inspector / Operations / Product API / Plugins в целом соблюдены: операции регистрируются в доменах/плагинах, Inspector читает только через разрешённые источники и list_handler_types, Product API изолирован, плагины используют фасад для capability.
- Блокеры для Stage D:
  - **P1:** убрать зависимость core от modules (`core/utils/operation.py` → вынести get_operation_id/set_operation_id в абстракцию или в модуль, который не импортируется из core).
- Желательно до Stage D:
  - **P2:** убрать или пометить legacy POST /admin/v1/devices/{id}/state и пути GET /admin/v1/devices*; убрать доменное имя "yandex" из _inventory_external_providers (например, получать список провайдеров из state или из списка плагинов без имён); ослабить или вынести в конфиг проверки "oauth" в plugin_manager.

---

## Часть 1. Core Invariants — сводка

| Проверка | Результат | Деталь |
|----------|-----------|--------|
| core/* не импортирует modules/plugins | **VIOLATION** | `core/utils/operation.py:11` — `from modules.request_logger.middleware`. |
| В core нет доменных терминов | **VIOLATION** | `core/plugin_manager.py:715-721` — "oauth" в логике флагов. Остальное — примеры в docstring, имена модулей (devices), конфиг (pg_user). |
| core/operations.py без доменной логики | **OK** | Только регистрация handlers, диспетчеризация, storage для операций. |
| CapabilityRegistry только метаданные | **OK** | Нет call/resolve/invoke. |

---

## Часть 2. Plugins & Capabilities — сводка

| Плагин | Прямые вызовы к другому плагину | Через фасад | OK/Violation |
|--------|----------------------------------|------------|--------------|
| yandex_smart_home | Нет вне oauth_provider | oauth_provider.py — все вызовы oauth_yandex.*, yandex_device_auth.* | OK |
| oauth_yandex | — | Собственные сервисы, logger | OK |
| yandex_device_auth | — | logger | OK |

capabilities_provided/required заданы в metadata (oauth_yandex:92, yandex_smart_home:75, yandex_device_auth:39).

---

## Часть 3. Operations — сводка

- Регистрация: oauth_yandex (on_start), yandex_smart_home operations.py (on_start), devices/operations.py (DevicesModule.start()). В admin — нет.
- Inspector: список операций только через `runtime.operations.list_handler_types()` (`modules/admin/services/introspection.py:225`).
- UI: типы операций частично берутся из Inspector (OperationsPage — кнопки из getOperationsAvailable()), частично захардкожены (DevicesPage, MappingPage — Sync, Check Online, set_state, mapping.*) — transitional.

---

## Часть 4. Inspector — сводка

- В `modules/admin/services/introspection.py`: все функции кроме get_inventory не вызывают `service_registry.call`. Используются plugin_manager, list_services(), http.list(), event_bus.list_subscriptions(), state, storage, operations.list_handler_types().
- get_inventory: вызывает `service_registry.call("admin.v1.devices.list")` и т.д. — документированное исключение.
- Нарушение: _inventory_external_providers() возвращает `["yandex"]` (строка 264) — доменное имя в Inspector.

---

## Часть 5. AdminModule — сводка

- Делает: auth, inspector endpoints, proxy /admin/v1/operations, webhook_test, admin.v1.devices.* (read + set_state).
- Не регистрирует operation handlers.
- Регистрирует legacy: GET /admin/v1/devices*, POST /admin/v1/devices/{id}/state и сервис admin.v1.devices.set_state (вызов devices.set_state) — нарушение границы «все мутации через Operations».

**Ответ на вопрос:** «Если добавить новый плагин, нужно ли менять AdminModule?» — **НЕТ.** Новый плагин регистрирует свои операции в on_start(); Inspector подхватывает типы через list_handler_types(); UI может показывать кнопки из getOperationsAvailable(). AdminModule менять не нужно.

---

## Часть 6. Product API — сводка

- Использует только доменные сервисы devices.list, devices.get.
- Не использует Inspector и Operations.
- Ручки только /api/v1/devices, /api/v1/devices/{id}.
- Модуль required=False. Отключение Product API не ломает Admin UI и Core.

---

## Часть 7. UI Contract — сводка

- GET: основной read-контур — inspector.ts (/admin/v1/inspector/*). Дополнительно: admin.ts (/admin/v1/auth/*), oauth.ts (/oauth/yandex/*), useYandexDeviceAuth/YandexDeviceAuthDialog (/yandex/auth/device/*) — transitional.
- ACTION: операции через operations.ts (POST /admin/v1/operations). Мутации устройств/маппингов идут через createOperation.
- Нет обращений к /admin/v1/devices, /admin/v1/yandex по коду api/inspector.ts и api/operations.ts (legacy пути убраны из основного потока).
- plugin_loaded / hasYandex в UI не проверяются (поиск по коду — только `if (!devices)` как проверка данных, не домена).
- Действия частично строятся из Inspector (OperationsPage — список типов из getOperationsAvailable()), частично — захардкоженные типы в DevicesPage/MappingPage.

---

## Финальный контрольный вопрос

**Можно ли: (1) удалить yandex_smart_home, (2) запустить Core, (3) открыть Admin UI, (4) не получить runtime error?**

**Ответ: ДА.**

- Core: yandex_smart_home не в BUILTIN_MODULES; плагины подгружаются отдельно. Удаление плагина не мешает старту Core.
- Admin UI: не импортирует плагины по имени; читает данные через Inspector (getPlugins, getOperationsAvailable, getInventory). Список плагинов и операций станет меньше; кнопки, зависящие от getOperationsAvailable(), покажут только оставшиеся типы. Строк с обязательным вызовом сервисов yandex_smart_home в UI нет — только вызовы createOperation({ type: "..." }), а типы либо из Inspector, либо захардкожены; при отсутствии handler операция завершится с ошибкой «unknown operation», а не runtime error при загрузке страницы.
- Страницы OAuth/Session (/oauth/yandex/*, /yandex/auth/device/*) при отключённых плагинах могут давать 404 при действиях пользователя, но не падение приложения при открытии UI.

Итог: архитектура выдерживает сценарий «удалить yandex_smart_home → запустить Core → открыть Admin UI» без runtime error.
