# Event: `operation_ready`

Сигнал: операция создана (или готова к повторному запуску) и должна быть подхвачена **OperationWorker**.

## Тип

Каноническое имя: константа `OPERATION_READY_EVENT_TYPE` в `core.operations.dedup_contract` (значение `"operation_ready"`).

## Payload (для подписчиков после `publish`)

Минимально:

| Поле | Тип | Обязательно | Описание |
|------|-----|-------------|----------|
| `type` | string | да | Должно совпадать с типом события (`operation_ready`). |
| `operation_id` | string | да | ID операции в подсистеме operations. |

Добавляется адаптером шины (не обязательно указывать издателю при `publish(type, dict)`):

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | string | ID записи события в EventBus; используется для claim + dedup по событию (см. ADR 001). |

Опционально (наблюдаемость, без требований со стороны worker):

| Поле | Тип | Описание |
|------|-----|----------|
| `operation_type` | string | Тип операции. |
| `created_at` | number | Unix time. |

См. также `OperationReadyPayload` в `core/events_schemas.py`.

## Издатели в репозитории

- `modules/admin/operations.py` — `_publish_operation_ready` (`sdk.operations_events.build_operation_ready_payload`)
- `modules/retry_policy/module.py` — повторная постановка при retry
- **Плагины:** `await self.publish_operation_ready(operation_id)` или
  `await self.runtime.api.publish_operation_ready(operation_id)` — без ручной сборки payload и без импорта `core`.

## SDK (плагины)

- `sdk.operations_events.OPERATION_READY_EVENT_TYPE`, `build_operation_ready_payload`
- `BasePlugin.publish_operation_ready` / `PluginAPI.publish_operation_ready`

## Поведение OperationWorker

Кратко: dedup по `id` (если есть) → claim → проверка `processed_op:{operation_id}` → `execute_operation_now` → `mark_event_processed` → терминальный persist → `mark_operation_processed`.

Подробно: `docs/adr/001-dedup-at-least-once-contract.md`.
