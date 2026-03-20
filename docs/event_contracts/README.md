# Event Contracts Index

Каталог **event contracts** (payload-схемы) в формате `.md`.

## Существующие события (задокументированные)

| Event type | Краткое описание | Producers | Consumers | Contract |
|---|---|---|---|---|
| `external.device_state_reported` | Событие о reported-состоянии внешнего устройства (snapshot или partial update). | `plugins/yandex_smart_home` (WS/REST sync/optimistic/polling fallback) и test/demo producers | `modules/devices`, `modules/automation` | [`external.device_state_reported.md`](./external.device_state_reported.md) |

## Примечание

В текущем репозитории в `docs/event_contracts/` задокументирован только контракт `external.device_state_reported`. Остальные event types могут существовать в runtime, но пока не имеют отдельного contract-файла в этом каталоге.

