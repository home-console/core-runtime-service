"""
Единый контракт dedup / at-least-once для операций и событий `operation_ready`.

Назначение
----------
- **Один источник правды** для формата ключей в storage и смысла «processed».
- Любой код (ядро, модули, тесты) должен опираться на константы и билдеры
  из этого модуля, а не дублировать строковые префиксы.

Модель доставки
---------------
1. **Событие шины** `operation_ready` доставляется с полем ``id`` — идентификатор
   записи события в EventBus (генерируется адаптером, см. ``Event.new`` в
   ``core/messaging.py``), если издатель не передал свой ``id`` явно.
2. **Claim** на событие (``claim_event(event_id, worker_id)``) координирует
   несколько воркеров; реализация — ``EventBusClaimManager`` / адаптер storage.
3. **DedupLayer** (namespace ``DEDUP_STORAGE_NAMESPACE``) хранит флаги
   «уже обработано» для:
   - **события** — по ``event_id`` (ключ ``processed_event:{event_id}``);
   - **операции** — по ``operation_id`` после **терминального** успешного
     persist (ключ ``processed_op:{operation_id}``).

Политика для операций (OperationWorker)
-----------------------------------------
- Перед выполнением: если ``processed_op:{operation_id}`` уже есть — выполнение
  не начинается (idempotent no-op для повторных ``operation_ready``).
- После ``storage.persist(result)`` и если ``result.status`` в
  ``TERMINAL_STATUSES`` — выставляется ``processed_op:{operation_id}``.

Политика для событий
--------------------
- Если в payload есть ``id``: до работы проверяется dedup по событию, затем
  claim; после успешного прохода выполнения операции — ``mark_event_processed``.
- Если ``id`` нет (устаревший или in-process путь): event-level dedup/claim не
  применяются; защита остаётся на уровне операции и attempt-claim в storage
  операций.

TTL
---
Значения в storage — строка с timestamp истечения (unix). По умолчанию
``DEFAULT_DEDUP_TTL_SECONDS``. Записи истёкшие по времени удаляются при чтении.

Связь с idempotency_key операции
--------------------------------
Поле ``Operation.idempotency_key`` — отдельный механизм на этапе **создания**
операции (модули idempotency); **не** подменяет ключи DedupLayer. Оба слоя
могут сосуществовать: idempotency предотвращает дубликаты сущностей, DedupLayer
— повторное **завершение** после at-least-once доставки.

Документация для авторов
------------------------
- ``docs/adr/001-dedup-at-least-once-contract.md`` — ADR и сценарии.
- ``docs/event_contracts/operation_ready.md`` — контракт payload.
- Строка типа события для плагинов: ``sdk.operations_events.OPERATION_READY_EVENT_TYPE``
  (в этом модуле реэкспорт для ядра и модулей).
"""

from __future__ import annotations

# Must match sdk.operations_events.OPERATION_READY_EVENT_TYPE (see tests/test_dedup_contract.py).
OPERATION_READY_EVENT_TYPE: str = "operation_ready"

# Storage namespace for DedupLayer (must match adapter get/set/delete namespace).
DEDUP_STORAGE_NAMESPACE: str = "dedup"

# Logical key prefixes inside that namespace (full storage key = prefix + id).
PROCESSED_OPERATION_KEY_PREFIX: str = "processed_op:"
PROCESSED_EVENT_KEY_PREFIX: str = "processed_event:"

DEFAULT_DEDUP_TTL_SECONDS: int = 3600


def storage_key_for_operation(operation_id: str) -> str:
    """Ключ в namespace ``dedup`` для терминально обработанной операции."""
    return f"{PROCESSED_OPERATION_KEY_PREFIX}{operation_id}"


def storage_key_for_event(event_id: str) -> str:
    """Ключ в namespace ``dedup`` для обработанного события (event bus id)."""
    return f"{PROCESSED_EVENT_KEY_PREFIX}{event_id}"


__all__ = [
    "DEFAULT_DEDUP_TTL_SECONDS",
    "DEDUP_STORAGE_NAMESPACE",
    "OPERATION_READY_EVENT_TYPE",
    "PROCESSED_EVENT_KEY_PREFIX",
    "PROCESSED_OPERATION_KEY_PREFIX",
    "storage_key_for_event",
    "storage_key_for_operation",
]
