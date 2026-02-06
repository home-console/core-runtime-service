from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Literal, Optional


ExecutionBackendId = Literal["in_process", "process", "container"]
ExecutionStatus = Literal["running", "ok", "error", "timeout", "killed", "cancelled"]


@dataclass
class ExecutionTrace:
    """
    Чистая модель трассы исполнения одной попытки выполнения операции.

    ВАЖНО:
    - Не содержит доменных идентификаторов (devices, users, plugins и т.п.)
    - Не содержит business-статусов
    - Привязана только к operation_id и execution_id
    """

    execution_id: str
    operation_id: str
    operation_type: str

    backend: ExecutionBackendId

    status: ExecutionStatus

    started_at: datetime
    finished_at: Optional[datetime]

    duration_ms: Optional[int]

    error_code: Optional[str]
    error_message: Optional[str]

    stderr_tail: Optional[str]  # max N chars

    # Cancellation metadata (D3.4)
    cancelled_at: Optional[datetime] = None
    cancel_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "operation_id": self.operation_id,
            "operation_type": self.operation_type,
            "backend": self.backend,
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "duration_ms": self.duration_ms,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "stderr_tail": self.stderr_tail,
            "cancelled_at": self.cancelled_at.isoformat() if self.cancelled_at else None,
            "cancel_reason": self.cancel_reason,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionTrace":
        return cls(
            execution_id=str(data["execution_id"]),
            operation_id=str(data["operation_id"]),
            operation_type=str(data["operation_type"]),
            backend=_parse_backend(data.get("backend")),
            status=_parse_status(data.get("status")),
            started_at=_parse_datetime(data.get("started_at")),
            finished_at=_parse_datetime_optional(data.get("finished_at")),
            duration_ms=int(data["duration_ms"]) if data.get("duration_ms") is not None else None,
            error_code=data.get("error_code"),
            error_message=data.get("error_message"),
            stderr_tail=data.get("stderr_tail"),
            cancelled_at=_parse_datetime_optional(data.get("cancelled_at")),
            cancel_reason=data.get("cancel_reason"),
        )


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        # epoch seconds
        return datetime.utcfromtimestamp(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            # fallback: try parse as epoch string
            try:
                return datetime.utcfromtimestamp(float(value))
            except Exception:
                pass
    # В крайнем случае — "сейчас", чтобы не падать из-за старых/битых данных
    return datetime.utcnow()


def _parse_datetime_optional(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    return _parse_datetime(value)


def _parse_backend(value: Any) -> ExecutionBackendId:
    if value in ("in_process", "process", "container"):
        return value  # type: ignore[return-value]
    return "in_process"


def _parse_status(value: Any) -> ExecutionStatus:
    if value in ("running", "ok", "error", "timeout", "killed", "cancelled"):
        return value  # type: ignore[return-value]
    return "error"


def make_execution_namespace_keys(operation_id: str, execution_id: str) -> Dict[str, str]:
    """
    Возвращает ключи для хранения трассы исполнения в storage namespace "execution".

    Структура:
      execution/
        traces/{execution_id}
        by_operation/{operation_id}/{execution_id}
    """
    trace_key = f"traces/{execution_id}"
    index_key = f"by_operation/{operation_id}/{execution_id}"
    return {"trace_key": trace_key, "index_key": index_key}

