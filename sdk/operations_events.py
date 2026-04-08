"""
События, связанные с operations и OperationWorker (G1).

Плагины импортируют только `sdk`; строка типа события и форма payload —
единый контракт с `core.operations.dedup_contract` (ядро реэкспортирует отсюда).
"""

from __future__ import annotations

from typing import Any

# Должно совпадать с использованием в core (см. tests/test_dedup_contract.py).
OPERATION_READY_EVENT_TYPE: str = "operation_ready"


def build_operation_ready_payload(operation_id: str, **extra: Any) -> dict[str, Any]:
    """
    Канонический payload для публикации `operation_ready`.

    Поля ``type`` и ``operation_id`` выставляются последними и перекрывают
    одноимённые ключи в ``extra``, если они были переданы по ошибке.

    EventBus при ``publish(event_type, payload)`` добавит в доставляемый подписчикам
    dict поле ``id`` (идентификатор записи события) — его не нужно указывать вручную.
    """
    if not operation_id or not isinstance(operation_id, str):
        raise ValueError("operation_id must be a non-empty str")
    out: dict[str, Any] = dict(extra)
    out["type"] = OPERATION_READY_EVENT_TYPE
    out["operation_id"] = operation_id
    return out


__all__ = ["OPERATION_READY_EVENT_TYPE", "build_operation_ready_payload"]
