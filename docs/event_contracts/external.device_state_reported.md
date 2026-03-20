## Event Overview

**Name:** `external.device_state_reported`  
**Domain:** `devices` / `integration`  
**Description:** Событие о **reported-состоянии** внешнего устройства. Содержит snapshot или partial update, используемый для reconcilliation в `modules/devices` и (при наличии mapping) для orchestration в `modules/automation`.

---

## Payload Schema (STRICT)

Ниже — формальная схема в JSON Schema-подобном виде. Валидатор/SDK должен поддерживать:
- `required` поля
- проверки типов
- разрешение `additionalProperties: true` (unknown keys допустимы)

```json
{
  "type": "object",
  "required": ["external_id", "state"],
  "properties": {
    "external_id": {
      "type": "string",
      "description": "External device identifier"
    },
    "state": {
      "type": "object",
      "description": "Reported device state (partial or full)"
    },
    "source": {
      "type": "string",
      "enum": ["ws", "rest", "optimistic", "polling"],
      "description": "Origin of the state update"
    },
    "online": {
      "type": "boolean",
      "description": "Device online status"
    },
    "timestamp": {
      "type": "number",
      "description": "Unix timestamp when event was generated"
    }
  },
  "additionalProperties": true
}
```

---

## Field Semantics

### `external_id`
- Уникальный id внешнего устройства (строка).
- **Обязателен.**
- Должен соответствовать `devices_mappings.external_id` для корректной работы `modules/automation` и для прямого reconciliation в `modules/devices`.

### `state`
- Содержит `reported` состояние устройства (полное или частичное).
- **Обязателен.**
- Структура определяется capabilities конкретного устройства/интеграции.
- `modules/devices`:
  - ожидает объект `dict`
  - мерджит/применяет входящие поля к `device.state.reported`
  - при расхождениях частично синхронизирует `device.state.desired` по ключам из входящего `state`

### `source`
- Происхождение апдейта и “доверенность” (`trust`) для downstream логики.
- В эталонном стандарте рекомендуется **всегда** указывать `source`.
- Допустимые значения:
  - `ws` — authoritative (WebSocket)
  - `rest` — snapshot / reconciliation (REST)
  - `polling` — fallback (polling)
  - `optimistic` — predicted/assumed (после отправки команды)

### `online`
- Булево online/offline (опционально).
- Если присутствует, `modules/devices` обновляет `device.online`.

### `timestamp`
- Unix timestamp (number) на момент генерации event producer’ом (опционально).
- Сейчас consumer’ы могут не использовать `timestamp`, но он важен для future dedup/order logic.

### Unknown fields
- Разрешены (`additionalProperties: true`).
- Привязка/валидация неизвестных полей не обязательна.

---

## Event Semantics

### Гарантии
- Событие означает: **“устройство изменило reported состояние”**.

### Не гарантируется
- порядок событий (events могут прийти out-of-order)
- уникальность (один и тот же смысл может быть опубликован несколько раз)
- полнота `state` (может быть partial update)

---

## Source Matrix (ОЧЕНЬ ВАЖНО)

Рекомендации для consumer’ов (в первую очередь `modules/devices`) по применению доверия и pending-семантике:

| `source` | Полный state | Надёжность | Использовать для pending |
|----------|-------------:|-----------:|--------------------------|
| `ws` | да | высокая | да |
| `rest` | да | средняя | осторожно |
| `polling` | да | средняя | осторожно |
| `optimistic` | нет | низкая | нет |

Примечание: текущая реализация в `modules/devices` может не различать pending-логику строго по `source`. Этот документ задаёт целевую архитектурную семантику для новых producer’ов и будущих улучшений.

---

## Examples

### 1) WS (authoritative)

```json
{
  "external_id": "lamp_1",
  "state": { "on": true, "brightness": 80 },
  "source": "ws",
  "online": true,
  "timestamp": 1710000000
}
```

### 2) REST snapshot

```json
{
  "external_id": "lamp_1",
  "state": { "on": true },
  "source": "rest",
  "online": true
}
```

### 3) Optimistic (predicted)

```json
{
  "external_id": "lamp_1",
  "state": { "on": true },
  "source": "optimistic",
  "online": true,
  "timestamp": 1710000001
}
```

### 4) Polling fallback

```json
{
  "external_id": "lamp_1",
  "state": { "on": true, "brightness": 50 },
  "source": "polling",
  "online": true
}
```

---

## Consumer Expectations

### `modules/devices` (reconciliation)
- Обновляет storage device state.
- При корректной будущей архитектуре должен:
  - использовать `source` для trust/pending semantics

### `modules/automation` (intent creation)
- При наличии mapping для `external_id` создаёт operation `automation.run`.
- Не гарантирует dedup (если producer’ы публикуют много одинаковых state events).

---

## Validation Rules (для SDK/валидации)

Минимальные правила:
1. `external_id` MUST быть `string`
2. `state` MUST быть `object`
3. `source` SHOULD быть предоставлен (если producer его знает)
4. unknown fields ALLOWED

---

## Known Issues (актуальные ограничения системы)
- Optimistic может быть indistinguishable без `source` (если producer не проставляет `source`).
- Pending может сбрасываться не строго по `source` (в текущей кодовой реализации).
- Дубликаты возможны из-за burst/реconciliation (WS+REST+optimistic/polling).

