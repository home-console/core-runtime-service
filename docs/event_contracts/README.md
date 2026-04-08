# Event Contracts Index

Каталог **event contracts** (payload-схемы) в формате `.md`.

## Существующие события (задокументированные)

| Event type | Краткое описание | Producers | Consumers | Contract |
|---|---|---|---|---|
| `external.device_state_reported` | Событие о reported-состоянии внешнего устройства (snapshot или partial update). | `plugins/yandex_smart_home` (WS/REST sync/optimistic/polling fallback) и test/demo producers | `modules/devices`, `modules/automation` | [`external.device_state_reported.md`](./external.device_state_reported.md) |
| `operation_ready` | Постановка операции в очередь OperationWorker; at-least-once dedup/claim см. ADR 001. | `modules/admin/operations`, `modules/retry_policy` | `core/operations/worker.py` | [`operation_ready.md`](./operation_ready.md) |

## Примечание

Полный индекс всех runtime event types не ведётся здесь; перечислены контракты с отдельным файлом. Для dedup/at-least-once см. также [`../adr/001-dedup-at-least-once-contract.md`](../adr/001-dedup-at-least-once-contract.md).

