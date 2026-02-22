# Инженерный аудит: plugins/yandex_smart_home как production distributed subsystem

**Дата:** 2025-02-22  
**Объект:** `core-runtime-service/plugins/yandex_smart_home`  
**Фокус:** архитектурные риски, state consistency, WebSocket reliability, ACL, failure scenarios. Без переписывания кода и косметических улучшений.

---

## 1. Executive summary

Плагин реализует синхронизацию устройств Яндекса через два источника: REST (OAuth/Quasar API) и WebSocket (Quasar). Состояние устройств проходит через event_bus в модуль devices, который пишет в storage (`devices`, `devices_external`, `devices_mappings`, `devices_external_pending_state`). Единого источника истины по времени обновления нет: REST snapshot и WS updates конкурируют без версионирования, периодический sync может перезаписать более свежий WS state. WebSocket loop при одновременном вызове `start()` может породить два runner’а (race). ACL для admin-only сервисов корректен при HTTP; внутренний sync (on_load, periodic, device_auth) обходит ACL по задумке. Критичные риски: перезапись state при periodic sync, возможный двойной WS loop, остановка reconnect после 10 ошибок подряд без автоматического восстановления.

---

## 2. Архитектурная схема

### 2.1 Границы компонентов

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  PLUGIN INTERNAL LOGIC                                                        │
│  plugin.py: on_load, on_start, _sync_devices_internal, _periodic_sync_loop    │
│  sync/device_sync.py: sync_devices → API → event_bus (discovered + state)     │
│  command_handler.py: internal.device_command_requested → API / optimistic    │
│  clients/yandex_quasar_ws.py: _run_loop → _consume_ws → event_bus (state)    │
└─────────────────────────────────────────────────────────────────────────────┘
         │                    │                      │
         ▼                    ▼                      ▼
┌─────────────────┐  ┌──────────────────┐  ┌─────────────────────────────────┐
│ OPERATIONS      │  │ SERVICE_REGISTRY │  │ EVENT_BUS                         │
│ operations.py   │  │ yandex.sync_*    │  │ external.device_discovered        │
│ handle_yandex_*  │  │ (admin_only)    │  │ external.device_state_reported    │
│ → call(service)  │  │ devices.*       │  │ internal.device_command_requested │
└─────────────────┘  └──────────────────┘  └─────────────────────────────────┘
         │                    │                      │
         └────────────────────┼──────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ DEVICES MODULE (consumers)                                                   │
│ handlers: handle_external_device_discovered → storage devices_external        │
│           handle_external_state → devices_external_pending_state | devices   │
│ services: create_device, set_state, auto_map_external, update_device_fields   │
└─────────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ STORAGE (namespaces: devices, devices_external, devices_mappings,              │
│          devices_external_pending_state, yandex)                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

- **Plugin internal:** вся логика синка, WS, команд; не пишет напрямую в storage устройств, только в `yandex.use_real_api` и через event_bus.
- **Operations layer:** только вызов `service_registry.call("yandex.sync_devices")` / `yandex.check_devices_online`; ACL проверяется при вызове (RequestContext).
- **Service_registry:** регистрация `yandex.sync_devices` (admin_only=True); при вызове без контекста — ForbiddenError.
- **Storage:** пишет только DevicesModule (handlers + services) и сам плагин (только `yandex.use_real_api`).
- **Event_bus:** плагин публикует; DevicesModule и automation подписаны.

### 2.2 Дублирование логики

| Участок | Admin operation handler | Periodic reconciliation | Initial sync |
|--------|---------------------------|--------------------------|---------------|
| Вызов sync | operations → `call("yandex.sync_devices")` | `_sync_devices_internal()` напрямую | `_sync_devices_internal()` в on_load |
| Реализация | Тот же зарегистрированный сервис `_sync_devices` → `_sync_devices_internal()` | Тот же `_sync_devices_internal()` | Тот же `_sync_devices_internal()` |
| Итог | Единая реализация: `_sync_devices_internal()` → DeviceSync.sync_devices() + service_registry.call("devices.auto_map_external") с SystemContext. Дублирования нет. |

### 2.3 Hidden side effects

- **Initial sync в on_load:** выполняется до `on_start`; при падении только логируется, регистрация сервисов не откатывается.
- **device_auth.linked:** помимо sync вызывает `storage.set("yandex", "use_real_api", {"enabled": True})`, затем `_sync_devices_internal()` и `quasar_ws.start()` — три эффекта в одном обработчике.
- **Optimistic update (flow.handle_post_send):** после отправки команды публикуется `external.device_state_reported` с ожидаемым state; DevicesModule применяет его к `devices` как «reported», без пометки, что это оптимистичное значение.
- **Periodic sync каждые 300 с:** публикует `device_discovered` и при наличии state — `device_state_reported` по всем устройствам из REST; порядок обработки событий в DevicesModule не гарантирует «сначала discovered, потом state» для одного устройства в одной итерации.

### 2.4 Single source of truth для device state

- **Внутреннее состояние устройства (reported/desired/pending):** формально хранится в `storage["devices"][internal_id].state`. Обновляется из:
  - `external.device_state_reported` (sync, WS, optimistic, poll fallback),
  - `devices.set_state` (user),
  - `devices.update_device_fields` (auto_map_external, reset_pending, pending_cleaner).
- **Временной приоритет не используется:** нет timestamp/version при записи; последняя запись выигрывает. Поэтому REST snapshot (periodic/initial sync) может перезаписать более новый WS state (см. блок 4).

---

## 3. State Model Audit

### 3.1 Точки записи

**Namespace `devices`:**

| Файл | Функция | Ключ | Условие |
|------|---------|------|---------|
| modules/devices/services.py | create_device | device_id | создание/обновление устройства |
| modules/devices/services.py | set_state | device_id | desired += state, pending=True, затем event internal.device_command_requested |
| modules/devices/services.py | auto_map_external | internal_id | после create_device + update_device_fields |
| modules/devices/services.py | update_device_fields | device_id | merge updates в документ |
| modules/devices/handlers.py | handle_external_state | internal_id | по mapping, обновление state.reported/desired, pending=False |
| modules/devices/pending_cleaner.py | cleanup_loop, clear_pending_manually | device_id | pending=False при timeout / ручной сброс |

**Namespace `devices_external`:**

| Файл | Функция | Ключ | Условие |
|------|---------|------|---------|
| modules/devices/handlers.py | handle_external_device_discovered | external_id | при каждом event external.device_discovered |

**Namespace `devices_mappings`:**  
`modules/devices/services.py` — create_mapping, auto_map_external (set), delete_mapping (delete).

**Namespace `devices_external_pending_state`:**  
`modules/devices/handlers.py` — set при отсутствии mapping в handle_external_state;  
`modules/devices/services.py` — delete в auto_map_external после применения pending к устройству.

### 3.2 Ответы по рискам

- **Может ли state потеряться?**  
  Да, в сценарии: periodic sync публикует по устройству только `device_discovered` (без state в payload или с пустым state) — в device_sync state_reported шлётся только если `device.get("state")`. Тогда в devices_external перезапишется запись полным payload; для devices внутреннее state не обновится из этого события. Если же позже приходит только `device_state_reported` с частичным state (например только `on`), то reported обновляется через update — остальные поля не трогаются. Потеря возможна при перезаписи более нового reported старым snapshot (см. ниже).

- **Может ли state перезаписаться пустым snapshot?**  
  Да. Initial или periodic sync вызывает device_sync; API может вернуть пустой список или устройство без state. Для каждого устройства публикуется device_discovered(data). handle_external_device_discovered делает `storage.set("devices_external", external_id, data)`. Если data без state или с пустым state — devices_external перезаписывается. Для уже замаппленного устройства handle_external_state вызывается только при публикации device_state_reported; если sync для этого устройства не публикует state_reported (нет state в device), то devices[internal_id].state не меняется в этом цикле. Но при следующем sync мы снова перезаписываем devices_external. Риск «пустого snapshot» для **devices** — когда sync всё же шлёт device_state_reported с пустым/частичным state и handle_external_state делает `old_state["reported"].update(reported_state)` и set; тогда старые ключи в reported остаются, новые перезаписываются. Полная «обнуление» reported возможно только если явно передать полный новый reported, что в коде не делается — везде update. Однако REST snapshot по времени может быть старее WS; тогда мы затираем более новый WS state старым REST (см. блок 4).

- **Stale reported/desired divergence?**  
  Да. handle_external_state при совпадении desired и reported сбрасывает pending; при расхождении синхронизирует desired с reported по полям из reported_state. Но источник события может быть старым (REST). Нет сравнения по времени между текущим reported и входящим.

- **Сценарий потери capabilities?**  
  Capabilities задаются при создании/обновлении устройства в auto_map_external через update_device_fields(internal_id, {"state": ..., "capabilities": ...}). handle_external_state обновляет только state (reported/desired/pending), не трогает capabilities. update_device_fields делает device.update(updates), т.е. частичное обновление. При применении только pending state в auto_map_external вызывается update_device_fields(..., {"state": device_state}) без capabilities — ключ capabilities не перезаписывается. Потеря capabilities возможна только при явной перезаписи документа устройства без capabilities (такой путь в аудите не найден).

- **Pending остаётся True навсегда?**  
  Нет гарантии сброса без дополнительных механизмов. Сброс происходит: (1) при приходе external.device_state_reported (handle_external_state ставит pending=False); (2) при reset_pending_on_error в command_handler; (3) pending_cleaner через 60 с; (4) clear_pending_manually. Если WS и REST не приходят, команда не отправлена (ошибка), а reset_pending_on_error не вызван для этого устройства — pending остаётся True до pending_cleaner (60 с) или ручного сброса. То есть «навсегда» — нет, но до 60 с — да.

---

## 4. WebSocket Reliability (yandex_quasar_ws.py)

### 4.1 Reconnect model

- Один долгоживущий loop: `_run_loop()`. При исключении (кроме CancelledError) — sleep(backoff), увеличение backoff (min(backoff*2, 60)), consecutive_errors++, затем снова цикл.
- После успешного connect и _consume_ws backoff и consecutive_errors обнуляются.
- _consume_ws при обрыве соединения пробрасывает исключение → выход из _consume_ws → исключение в _run_loop → backoff и повтор.

### 4.2 Backoff

- Начальный 1.0 с; после ошибки `backoff = min(backoff * 2, 60)`; дополнительный sleep(backoff + random.random()) и снова `backoff = min(backoff * 2, 30.0)` — дублирование увеличения и два разных потолка (60 и 30).
- В _consume_ws свой backoff_seconds (1..60), сбрасывается в 1 при успешном connect.

### 4.3 Failure scenarios

- Нет cookies / неверные cookies: логирование, sleep(30), continue — бесконечные попытки без ограничения.
- После 10 последовательных ошибок: логирование и `break` — loop завершается, повторных подключений нет до следующего start().
- stop_event: проверяется в цикле и перед sleep; при cancel runner’а — CancelledError, выход.

### 4.4 Memory / sessions

- _session создаётся в _consume_ws (при смене cookies или если session closed) и не закрывается при нормальном выходе из _consume_ws по исключению — закрытие только в stop(). При долгом цикле reconnect старая session может висеть до следующей смены cookies или stop.
- _subscribers и _devices — словари, растут при подписках и обновлениях; unsubscribe только через возвращённый callback. Утечка при отсутствии отписок ограничена размером множества устройств/подписок.
- asyncio.create_task(result) в _publish_state для callback’ов — создаётся задача без привязки к _tasks плагина; при unload плагина эти задачи не отменяются (мелкий риск накопления).

### 4.5 stop_event и отмена

- stop() выставляет _stop_event, отменяет _runner, ждёт его, закрывает _ws и _session. Корутина при отмене пробрасывает CancelledError — корректно.
- В _run_loop и _consume_ws при await asyncio.sleep(backoff) отмена обрабатывается (break).

### 4.6 Ответы

- **Reconnect storm?** Возможен при быстрых падениях (например, 401/403 в цикле): backoff растёт до 60 с, но после 10 ошибок цикл выходит и storm прекращается. До этого — до 10 попыток с растущим backoff.
- **Silent dead connection?** Да. После 10 последовательных ошибок loop завершается без повторного start(). Пользователь не узнает без логов; восстановление только при новом start() (рестарт плагина или повторная device auth).
- **Session leak?** При частой смене cookies или пересоздании session в _consume_ws старая session закрывается только при следующей итерации или при stop(). В одной итерации при исключении до закрытия session возможна утечка одной сессии до следующего входа в _consume_ws или stop().
- **Multiple WS loop?** Да, race: start() не атомарен. Два одновременных вызова могут оба увидеть _runner None или done и оба вызвать create_task(_run_loop()); _runner сохранит только один task, второй продолжит работать без учёта в _runner и не будет отменён в stop().

---

## 5. Sync Consistency Model

### 5.1 _sync_devices_internal()

- Вызывает device_sync.sync_devices() (REST/Quasar список устройств), затем под SystemContext — service_registry.call("devices.auto_map_external", provider="yandex"). Исключения логируются, не пробрасываются.

### 5.2 device_sync.sync_devices()

- Проверяет yandex.use_real_api; получает устройства (Quasar или OAuth API); для каждого публикует external.device_discovered(device) и при наличии state — external.device_state_reported({external_id, state}).

### 5.3 external.device_discovered / external.device_state_reported

- DevicesModule: handle_external_device_discovered → set("devices_external", external_id, data). handle_external_state → при отсутствии mapping set("devices_external_pending_state", ...); при наличии mapping — get device, обновление state, set("devices", internal_id, device).

### 5.4 Ответы

- **Guaranteed convergence?** Нет. Нет версий/timestamp; последняя запись выигрывает. Сходимость к одному состоянию не гарантирована при конкурирующих источниках.
- **REST snapshot затирает более новый WS state?** Да. Periodic sync публикует device_discovered и device_state_reported из REST. handle_external_state делает reported.update(reported_state) и set(devices). Если REST отстал от WS, более новый WS state будет перезаписан старым REST.
- **Конфликт periodic sync и live WS?** Да. Оба пишут в devices по одному internal_id без координации; возможен oscillating state при чередовании REST и WS обновлений (например, разные значения on каждые 5 мин от sync и в реальном времени от WS).
- **Oscillating state?** Возможно при периодическом REST и частых WS обновлениях с разными значениями.

---

## 6. ACL / Security Boundaries

### 6.1 Admin operations

- yandex.sync_devices, yandex.check_devices_online, yandex.subscribe_device_updates зарегистрированы с admin_only=True. При вызове через service_registry обёртка вызывает policy_engine.enforce_admin(ctx). Если ctx is None (нет RequestContext) — ForbiddenError.

### 6.2 Где вызывается service_registry.call

- Plugin: logger, devices.auto_map_external (с SystemContext в _sync_devices_internal), yandex.sync_devices только через operation handler (с контекстом HTTP).
- Operations: handle_yandex_sync → call("yandex.sync_devices") — контекст задаётся при выполнении операции (HTTP).

### 6.3 Bypass ACL через internal calls

- _sync_devices_internal() не вызывает service_registry.call("yandex.sync_devices"); он вызывает device_sync.sync_devices() и call("devices.auto_map_external") с явным set_current_auth_context(SystemContext). То есть sync по расписанию и при device_auth не идёт через admin-only сервис — это задуманный внутренний путь. Обход ACL для «админского» sync только через прямой вызов _sync_devices_internal (доступен только коду плагина).

### 6.4 Malicious plugin

- Другой плагин может вызвать service_registry.call("yandex.sync_devices") без контекста → ForbiddenError. Чтобы пройти, нужен привилегированный контекст: RequestContext с admin или SystemContext. Установить SystemContext может любой код в процессе (create_system_context + set_current_auth_context). То есть в рамках одного процесса «злонамеренный» плагин может установить SystemContext и вызвать yandex.sync_devices — граница доверия на уровне процесса.

---

## 7. Failure Simulation

| Сценарий | Поведение | Потеря данных? | Self-healing? | Ручное вмешательство? |
|----------|-----------|----------------|---------------|------------------------|
| **A. WS падает на 10 минут** | _consume_ws падает по исключению, _run_loop делает backoff и повторные попытки. Через 10 минут при успешном connect цикл продолжается. | Нет (данные в devices уже есть; за 10 мин новые WS обновления не пришли). | Да (reconnect). | Нет. |
| **B. WS падает каждые 15 с** | Ошибки подряд; после 10 раз _run_loop выходит (break). | Нет. | Нет — loop завершён. | Да — рестарт плагина или повторный start() (например, device auth). |
| **C. REST snapshot возвращает пустой state** | device_sync публикует device_discovered с payload без/с пустым state; device_state_reported для этого устройства может не шться. devices_external перезаписывается; devices[internal_id].state не обновляется из этого sync. | Частично: devices_external может стать без state; внутренний reported не обнуляется, но и не обновляется из этого sync. | Нет автоматического «отката» devices_external. | Обычно не требуется; следующий успешный sync или WS обновит. |
| **D. Mapping создаётся позже** | WS присылает state_reported до auto_map_external; handle_external_state не находит mapping → пишет в devices_external_pending_state. После auto_map_external pending применяется к устройству и ключ pending_state удаляется. | Нет. | Да (применение при создании маппинга). | Нет. |
| **E. storage.set выбрасывает исключение** | В handlers/services исключение пробрасывается; вызывающий код (event handler, operation) может упасть. Нет retry/транзакций. State может остаться непоследовательным (например, devices обновлён, devices_external — нет). | Возможна рассинхронизация или потеря одного из обновлений. | Нет. | Зависит от того, какой set упал и как обрабатываются ошибки выше. |
| **F. Quasar API меняет формат states** | Парсинг в DeviceTransformer или в WS может выбросить или вернуть неполный state. Ошибки логируются, часть обновлений может не дойти до storage. | Частичная потеря или некорректный state (например, пустой reported). | Нет. | Нужна адаптация кода под новый формат. |

---

## 8. Production Readiness Score (1–10)

| Критерий | Оценка | Комментарий |
|----------|--------|-------------|
| State consistency | 4 | REST vs WS без версий; periodic sync может затирать более новый WS state; возможны колебания. |
| WS stability | 5 | Нормальный reconnect и backoff; после 10 ошибок — тихий выход; возможен двойной loop при race start(). |
| Convergence guarantee | 3 | Нет гарантии сходимости при двух источниках записи без координации. |
| Recovery after restart | 7 | После рестарта плагина initial sync и при необходимости WS start() восстанавливают работу. |
| Memory safety | 6 | Потенциальная утечка одной session до следующего connect/stop; callback tasks не в _tasks плагина. |
| Race safety | 4 | start() не атомарен — возможны два _run_loop; запись в devices без блокировок. |
| Isolation boundaries | 7 | ACL для HTTP соблюдается; внутренний sync по дизайну без ACL; доверие на уровне процесса. |

**Общий production score: 5/10**

---

## Критические риски

1. **REST snapshot перезаписывает более новый WS state** — нет версий/timestamp; periodic sync публикует device_state_reported из REST и handle_external_state перезаписывает reported; более свежий WS state может быть потерян.
2. **WebSocket loop после 10 последовательных ошибок завершается навсегда** — тихий выход без повторного start(); восстановление только рестартом плагина или повторным событием device_auth.
3. **Race при двух одновременных start()** — неатомарная проверка _runner; возможны два активных _run_loop, один из которых не отменяется в stop().

## Средние риски

4. **Двойное увеличение backoff в _run_loop** — после sleep(backoff) ещё раз backoff = min(backoff*2, 30); потолки 60 и 30 в разных местах — путаница и возможный излишне долгий backoff.
5. **Session в WS** — при исключении внутри _consume_ws до закрытия соединения старая _session может не закрыться до следующей итерации или stop(); утечка одной сессии.
6. **Callback в _publish_state** — asyncio.create_task(cb) без добавления в _tasks плагина; при unload задачи не отменяются.
7. **Pending до 60 с** — если WS/REST не приходят и reset_pending_on_error не вызван, pending сбрасывается только pending_cleaner’ом (60 с); UX «зависшей» команды.

## Низкие риски

8. **Order of events** — в одном sync для устройства сначала device_discovered, потом device_state_reported; подписчики event_bus могут обработать в разном порядке — теоретическая рассинхронизация.
9. **Pending_cleaner task** — не сохраняется в модуле devices и не отменяется при stop() модуля; задача продолжает жить после выгрузки (низкий приоритет).
10. **Optimistic update без метки** — handle_external_state не различает «реальный» reported и оптимистичный; для UI это обычно приемлемо.

---

**Top 3 архитектурных плюса:**  
1. Единая реализация sync (_sync_devices_internal) для admin, periodic и initial sync.  
2. Чёткое разделение: плагин только публикует события; запись в storage устройств только в DevicesModule.  
3. Pending state при отсутствии mapping с последующим применением при auto_map_external и pending_cleaner для зависших команд.

---

## 9. Рекомендации (только архитектурные)

1. **State / sync:** Ввести версию или timestamp при обновлении state в devices (или в событии device_state_reported) и в handle_external_state применять обновление только если входящее новее текущего — чтобы исключить перезапись более нового WS state старым REST snapshot.
2. **WebSocket:** Сделать start() атомарным (например, asyncio.Lock) и при достижении max consecutive errors не выходить из _run_loop навсегда, а переходить в длительный backoff (например, sleep 5–10 мин) и повторять попытки, либо явно уведомлять (событие/метрика) о «WS остановлен по ошибкам» для внешнего перезапуска.
3. **Границы записи:** Зафиксировать в контракте, что единственный писатель в devices/devices_external для device state — DevicesModule; плагин не пишет в эти namespace, только публикует события. Это уже соблюдается, но полезно для будущих изменений.

---

*Аудит выполнен по текущей реализации без предложений по косметическим правкам и без требования переписать подсистему.*
