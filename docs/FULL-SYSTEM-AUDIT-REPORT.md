# Полный аудит системы HomeConsole Core Runtime

**Дата:** 2026-02-02  
**Цель:** Максимально выявить проблемы, которые могут подвести в проде.

---

## Критические (P0) — могут сломать систему или безопасность

### 1. Изоляция плагинов не применяется (обход StorageProxy и ServiceProxy)

**Файлы:** `core/plugin_manager.py` (94–107), все плагины (`plugins/oauth_yandex/plugin.py`, `plugins/yandex_smart_home/*`, `plugins/yandex_device_auth/*` и др.)

**Суть:** PluginManager выставляет `plugin.storage = StorageProxy(...)` и `plugin.services = ServiceProxy(...)`, но плагины везде используют **`self.runtime.storage`** и **`runtime.service_registry`** напрямую. Прокси не используются.

**Последствия:**
- Любой плагин может читать/писать любой namespace (oauth_yandex, yandex, devices и т.д.) — нет изоляции данных.
- Ограничения ServiceProxy (DEFAULT_ALLOWED_SERVICES) не действуют — плагин может вызывать любые сервисы, в т.ч. admin.*.

**Рекомендация:** Либо перевести все плагины на `self.storage` / `self.services` и гарантировать, что `runtime.storage`/`runtime.service_registry` плагинам не передаются, либо убрать прокси и явно задокументировать, что изоляция не обеспечивается.

---

### 2. StorageProxy несовместим с Core Storage API

**Файл:** `core/plugin_isolation.py` (82–127)

**Суть:** StorageProxy вызывает:
- `self._storage.get(namespaced_key, default)` — у Core Storage сигнатура `get(namespace, key)`, нет аргумента `default`. Фактически передаётся `(namespace="oauth_yandex:tokens", key=None)` → ValueError.
- `self._storage.put(namespaced_key, value)` — у Storage есть только `set(namespace, key, value)`, метода `put` нет → AttributeError.
- `self._storage.delete(namespaced_key)` — у Storage `delete(namespace, key)` с двумя аргументами → TypeError.
- `self._storage.exists(...)`, `self._storage.keys(...)` — у Storage таких методов нет.

**Последствия:** Если плагин начнёт использовать `self.storage` (прокси), все вызовы get/put/delete/exists/keys упадут.

**Рекомендация:** Либо переписать StorageProxy под API Core Storage (`get(ns, key)`, `set(ns, key, value)`, `delete(ns, key)`, `list_keys(ns)`), либо ввести отдельный «плагинный» интерфейс и внутри прокси маппить его в вызовы Storage с фиксированным namespace плагина.

---

### 3. ServiceRegistry.clear() не очищает _service_acl

**Файл:** `core/service_registry.py` (385–389)

**Суть:** В `clear()` очищаются только `_services` и `_deprecated`. Словарь `_service_acl` не трогается.

**Последствия:** После `clear()` при последующей регистрации сервисов с ACL метаданные ACL могут смешиваться со старыми записями; возможны неожиданные проверки прав по «призрачным» сервисам.

**Рекомендация:** В `clear()` добавить `self._service_acl.clear()`.

---

### 4. ServiceRegistry.unregister() не удаляет запись из _service_acl

**Файл:** `core/service_registry.py` (278–285)

**Суть:** При `unregister(service_name)` удаляется только запись из `_services`. Запись в `_service_acl` и `_deprecated` остаётся.

**Последствия:** Остаются «висячие» метаданные ACL и deprecated для несуществующих сервисов.

**Рекомендация:** В `unregister()` дополнительно выполнять `self._service_acl.pop(service_name, None)` и `self._deprecated.pop(service_name, None)`.

---

### 5. StorageWithStateMirror: рассинхрон при падении state_engine после storage.set()

**Файл:** `core/storage_mirror.py` (49–78)

**Суть:** В `set()` сначала вызывается `storage.set()`, затем `state_engine.set()`. Если `storage.set()` прошёл, а `state_engine.set()` выбросил исключение, откат storage не выполняется.

**Последствия:** В storage уже новое значение, в state_engine — старое. Кэш state_engine перестаёт соответствовать источнику истины.

**Рекомендация:** Либо оборачивать оба вызова в транзакцию/компенсирующие действия (откат storage при падении state_engine), либо явно документировать и обрабатывать «частичный» успех (например, помечать ключ в state как «грязный» и перечитывать из storage при следующем get).

---

### 6. ACL: enforce_policy при ctx=None не проверяет доступ (fail-open)

**Файл:** `core/acl.py` (73–87)

**Суть:** В `enforce_policy(ctx, resource, obj)` при `ctx is None` функция сразу выходит без проверки. В коде указано: «Если ctx None — считается trusted internal».

**Последствия:** Если по ошибке вызов с границы API уйдёт с `ctx=None` (например, из-за сброса контекста или бага в middleware), проверка политики будет пропущена.

**Рекомендация:** На boundary-слое гарантировать, что внутренние вызовы явно помечаются (например, SystemContext), а для HTTP всегда передаётся ненулевой контекст. Либо ужесточить: при неизвестном ресурсе не делать no-op, а требовать явной политики.

---

### 7. Rate limit: fail-open при любой ошибке

**Файл:** `modules/api/auth/rate_limiting.py` (98–111)

**Суть:** При любом исключении в `rate_limit_check()` возвращается `True` (лимит не превышен), запрос разрешается.

**Последствия:** При сбоях storage или логирования атакующий может обойти ограничение по числу попыток.

**Рекомендация:** Рассмотреть fail-closed для auth rate limit (при ошибке считать лимит превышенным или возвращать 503), либо разделить поведение для «auth» и «api» и документировать.

---

## Высокий приоритет (P1) — стабильность и корректность

### 8. Двойной timeout в call_with_timeout

**Файл:** `core/service_registry.py` (328–360)

**Суть:** `call_with_timeout(service_name, timeout=T, ...)` оборачивает `self.call(...)` в `asyncio.wait_for(..., timeout=T)`. Внутри `call()` при заданном `default_timeout` уже используется свой `wait_for`. Итоговый лимит — min(default_timeout, T). Документация этого не поясняет.

**Последствия:** Ожидание «ровно T секунд» может не сбыться, если default_timeout меньше.

**Рекомендация:** В докстринге описать, что действует минимум из двух таймаутов; либо в `call_with_timeout` не применять внутренний default_timeout для этого вызова.

---

### 9. IntegrationRegistry без блокировки

**Файл:** `core/integration_registry.py`

**Суть:** `_integrations` — обычный dict, операции register/unregister/list не защищены lock’ом.

**Последствия:** При одновременных вызовах из разных корутин возможны гонки (например, итерация по изменяемому dict). В asyncio одна задача, но при yield между операциями другая может изменить реестр.

**Рекомендация:** Использовать `asyncio.Lock()` для всех изменений и чтений, как в ServiceRegistry, либо явно документировать однопоточность использования.

---

### 10. request_logger middleware читает request.body() до обработчика

**Файл:** `modules/request_logger/middleware.py` (117–132)

**Суть:** В DEBUG middleware вызывает `await request.body()`, потребляя тело запроса. Поведение обработчика зависит от того, кэширует ли Starlette/FastAPI body после первого чтения.

**Последствия:** Если в другой версии фреймворка body не кэшируется, обработчики могут получить пустое тело.

**Рекомендация:** Явно зависеть от контракта «body после первого read доступен снова» или не читать body в middleware, а только логировать метаданные; при необходимости — копировать в request.state после первого read.

---

### 11. operations.execute() проглатывает тип исключения

**Файл:** `core/operations.py` (274–281)

**Суть:** При любом исключении в handler в `operation.error` попадает только `message=str(e)` и не сохраняется код/тип. Retry проверяет только `error.code` из фиксированного набора.

**Последствия:** Сложнее различать повторяемые и не повторяемые ошибки; при логировании теряется тип исключения.

**Рекомендация:** Сохранять в OperationError хотя бы `error_type=type(e).__name__` и при необходимости маппить в коды (timeout, network, …) для retry.

---

### 12. Health check и get_metrics раскрывают внутренние детали

**Файл:** `core/runtime.py` (243–244, 348–353)

**Суть:** В `health_check()` в ответ попадает `checks["storage_error"] = str(e)`; в `get_metrics()` — `metrics["storage"]["error"] = str(e)`. Исключения из БД/адаптеров могут содержать пути, имена таблиц, фрагменты запросов.

**Последствия:** Утечка информации об инфраструктуре через публичные или полупубличные endpoint’ы.

**Рекомендация:** В ответах наружу отдавать только коды/обобщённые сообщения; полный текст исключения — только в логах.

---

### 13. Remote services (remote_logger, remote_metrics) отдают str(exc) в HTTP 500

**Файлы:** `core/remote_services/remote_logger.py`, `core/remote_services/remote_metrics.py`

**Суть:** В обработчиках при ошибках делается `raise HTTPException(status_code=500, detail=str(exc))`.

**Последствия:** В ответах клиенту могут уходить трассировки и внутренние сообщения.

**Рекомендация:** В production не отдавать `str(exc)` в `detail`; логировать полный exception, клиенту отдавать нейтральное сообщение.

---

### 14. register_with_acl: versioned_name после register()

**Файл:** `core/service_registry.py` (220–225)

**Суть:** После `await self.register(service_name, wrapped, version=version)` переменная `versioned_name` вычисляется локально как `f"{service_name}.{version}" if version else service_name`. В `register()` имя строится так же, но если там когда-то изменится логика, ключ в `_service_acl` может не совпасть с ключом в `_services`.

**Последствия:** Потенциальная рассинхронизация имён при рефакторинге.

**Рекомендация:** Вычислять versioned_name в одном месте (например, вспомогательная функция) и использовать при регистрации и при записи в _service_acl.

---

## Средний приоритет (P2) — архитектура и долгосрочные риски

### 15. Core зависит от контракта operation_context (не от modules)

**Файл:** `core/utils/operation.py` — импортирует `core.operation_context.get_operation_id/set_operation_id`. Провайдер выставляется модулем request_logger при старте.

**Суть:** Если request_logger не запущен или не выставил провайдер, `get_operation_id()` возвращает None. Логирование в `operation()` всё равно использует свой `operation_id`; но корреляция с HTTP-запросами может пропадать.

**Рекомендация:** Явно описать в документации зависимость: для корреляции HTTP и system-операций нужен request_logger и установка провайдера.

---

### 16. Inspector знает доменное имя "yandex"

**Файл:** `modules/admin/services/introspection.py` (261–264)

**Суть:** `_inventory_external_providers()` возвращает захардкоженный список `["yandex"]`.

**Последствия:** Добавление новой интеграции без имени "yandex" потребует правок в Inspector; нарушение принципа «Inspector не знает доменных имён».

**Рекомендация:** Получать список провайдеров из state/storage или из списка плагинов/интеграций без захардкоженных имён.

---

### 17. Plugin_manager: доменная логика по "oauth" в manifest

**Файл:** `core/plugin_manager.py` (715–721)

**Суть:** Флаги интеграции определяются по строкам из manifest ("requires_oauth" и т.д.). В коде явно перечислены строки "requires_oauth", "beta" и т.д. — это не чисто «только из manifest», а интерпретация имён.

**Рекомендация:** Уже учтено в ARCHITECTURE-AUDIT-RESULT; при желании вынести маппинг строк в конфиг или оставить как документированное исключение.

---

### 18. Legacy POST /admin/v1/devices/{id}/state и GET /admin/v1/devices*

**Файл:** `modules/admin/module.py` (190–239)

**Суть:** Мутация состояния устройства через прямой HTTP и вызов `devices.set_state` в обход Operations; read-пути дублируют Inspector.

**Рекомендация:** Пометить как deprecated и постепенно переводить на Operations; либо явно задокументировать как legacy-контракт.

---

### 19. Admin UI захардкоживает типы операций

**Файлы:** `admin-ui-service/src/pages/DevicesPage.tsx`, `MappingPage.tsx` и др.

**Суть:** Типы вроде `yandex.sync_devices`, `device.set_state`, `device.mapping.*` заданы в коде, а не только из getOperationsAvailable().

**Последствия:** Новые типы операций не появятся в UI без правок фронта.

**Рекомендация:** По возможности строить действия из Inspector; оставшиеся хардкоды явно пометить и документировать.

---

## Низкий приоритет (P3) и прочее

### 20. OAuth/device auth UI не переведены на Inspector/Operations

**Файлы:** admin-ui-service oauth.ts, useYandexDeviceAuth, YandexDeviceAuthDialog

**Суть:** Экраны OAuth/Session ходят на /oauth/yandex/* и /yandex/auth/device/*. При отключении соответствующих плагинов эти запросы дадут 404.

**Рекомендация:** Документировать зависимость; при отключении плагинов показывать понятное сообщение в UI.

---

### 21. get_inventory зависит от admin.v1.devices.*

**Файл:** `modules/admin/services/introspection.py` (238–253)

**Суть:** get_inventory вызывает `service_registry.call("admin.v1.devices.list", ...)` и т.д. Удаление или переименование этих сервисов сломает inventory.

**Рекомендация:** Явно зафиксировать контракт в документации; при рефакторинге admin.v1.devices обновлять Inspector.

---

### 22. Множество голых except / except Exception

**По кодовой базе**

**Суть:** Во многих местах используется `except Exception` с `pass` или только логированием. Ошибки могут маскироваться.

**Рекомендация:** Сужать типы перехватываемых исключений; где нужно — пробрасывать дальше или логировать с уровнем error и контекстом.

---

### 23. base_plugin: assert self._runtime is not None в property runtime

**Файл:** `core/base_plugin.py` (59–62)

**Суть:** При доступе к `plugin.runtime` до установки runtime из менеджера или после unload сработает AssertionError. В production assert может быть отключён.

**Рекомендация:** Заменить на явную проверку и выброс понятного исключения (например, RuntimeError), не полагаться на assert.

---

## Сводная таблица

| # | Критичность | Краткое описание |
|---|-------------|------------------|
| 1 | P0 | Изоляция плагинов не работает — везде используется runtime.storage / service_registry |
| 2 | P0 | StorageProxy API не совместим с Core Storage |
| 3 | P0 | ServiceRegistry.clear() не очищает _service_acl |
| 4 | P0 | ServiceRegistry.unregister() не чистит _service_acl и _deprecated |
| 5 | P0 | StorageWithStateMirror — рассинхрон storage/state_engine при падении после set |
| 6 | P0 | ACL enforce_policy при ctx=None — fail-open |
| 7 | P0 | Rate limit при ошибке — fail-open |
| 8 | P1 | Двойной timeout в call_with_timeout, нет ясной документации |
| 9 | P1 | IntegrationRegistry без lock |
| 10 | P1 | request_logger middleware читает body — зависимость от кэша фреймворка |
| 11 | P1 | operations.execute не сохраняет тип/код исключения |
| 12 | P1 | health_check/get_metrics раскрывают str(e) наружу |
| 13 | P1 | remote_* отдают str(exc) в HTTP 500 |
| 14 | P1 | versioned_name в register_with_acl дублируется |
| 15–19 | P2 | Архитектурные и legacy моменты (operation_context, Inspector, admin UI) |
| 20–23 | P3 | Зависимости UI, голые except, assert в base_plugin |

---

## Рекомендуемый порядок исправлений

1. **Немедленно (P0):**  
   - Исправить `ServiceRegistry.clear()` и `unregister()` (п. 3, 4).  
   - Привести изоляцию плагинов в соответствие с реальностью: либо перевести плагины на `self.storage`/`self.services` и поправить API StorageProxy (п. 1, 2), либо убрать прокси и задокументировать отсутствие изоляции.  
   - Добавить откат или явную обработку при падении state_engine в StorageWithStateMirror (п. 5).  
   - Уточнить политику ACL при ctx=None и rate limit при ошибках (п. 6, 7).

2. **Краткосрочно (P1):**  
   Документировать/исправить таймауты, блокировки, логирование ошибок и утечку деталей в health/metrics и remote_* (п. 8–14).

3. **Среднесрочно (P2–P3):**  
   Рефакторинг Inspector, admin legacy, UI и обработки исключений по списку выше.
