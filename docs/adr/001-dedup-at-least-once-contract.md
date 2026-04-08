# ADR 001: At-least-once, dedup и событие `operation_ready`

**Статус:** принято  
**Дата:** 2026-04-05  
**Область:** `core/operations` (OperationWorker, DedupLayer), EventBus, издатели `operation_ready`

## Контекст

Доставка событий и выполнение операций — **at-least-once**: повторы возможны после рестарта, таймаутов и реплея. Без явного контракта легко получить двойные side effects или «тихие» пропуски.

## Решение

### 1. Два уровня защиты

| Уровень | Механизм | Идентификатор |
|--------|-----------|----------------|
| Событие в шине | DedupLayer + claim в EventBus | `id` события (см. ниже) |
| Операция | DedupLayer после терминального persist | `operation_id` |

Константы и формат ключей — **единственный источник правды**: модуль `core.operations.dedup_contract`.

### 2. Ключи в storage

- Namespace: `dedup` (`DEDUP_STORAGE_NAMESPACE`).
- Операция: `processed_op:{operation_id}`.
- Событие: `processed_event:{event_id}`.

Значение — строка с unix timestamp истечения; TTL по умолчанию 3600 с (`DEFAULT_DEDUP_TTL_SECONDS`).

### 3. Поле `id` у `operation_ready`

При вызове `event_bus.publish(type, payload)` адаптер (например `InMemoryEventBus`) создаёт запись события и **всегда добавляет** в payload для подписчиков поле `id` — идентификатор события в хранилище шины. Издатель может передать свой `id` только в форме «полного» dict-первого аргумента `publish` (см. `core/messaging.py`).

OperationWorker использует `payload["id"]` для:

1. раннего dedup (`is_event_processed`);
2. `claim_event(event_id, worker_id)`;
3. `mark_event_processed` после успешного прохода.

Если `id` отсутствует (нестандартный bus), event-level dedup/claim пропускаются; остаются claim попытки операции и dedup по `operation_id`.

### 4. Когда ставится `processed_op`

После успешного `storage.persist(result)` операции, если `result.status` входит в `TERMINAL_STATUSES` (completed / failed / cancelled). Это означает: «терминальный исход уже зафиксирован»; повторные `operation_ready` для той же операции не должны снова запускать выполнение.

### 5. Связь с `idempotency_key`

`Operation.idempotency_key` — отдельный контур (создание операций, модули idempotency). **Не** заменяет ключи DedupLayer и **не** должен совпадать с `processed_op:*` без явной договорённости на уровне продукта.

### 6. Константа типа события и публикация из плагинов

Каноническое определение строки — **`sdk.operations_events.OPERATION_READY_EVENT_TYPE`**; ядро реэкспортирует её через `core.operations.dedup_contract`.

Плагины (только импорт `sdk`): `build_operation_ready_payload`, либо готовый метод **`BasePlugin.publish_operation_ready(operation_id, **extra)`** — без дублирования строк и без доступа к `core`.

## Последствия

- Любое изменение префиксов или namespace ломает совместимость с уже записанным storage — менять только с миграцией или bump версии.
- Новые издатели `operation_ready` должны использовать `OPERATION_READY_EVENT_TYPE` и минимальный payload из `docs/event_contracts/operation_ready.md`.

## Ссылки

- `core/operations/dedup_contract.py`
- `docs/event_contracts/operation_ready.md`
