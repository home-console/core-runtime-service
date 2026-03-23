from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any


@dataclass
class Event:
    id: str
    type: str
    payload: dict[str, Any]
    created_at: float
    processed: bool = False
    processed_at: float | None = None

    @classmethod
    def new(cls, event_type: str, payload: dict[str, Any]) -> "Event":
        return cls(
            id=f"evt-{uuid.uuid4().hex}",
            type=str(event_type),
            payload=dict(payload),
            created_at=time.time(),
            processed=False,
            processed_at=None,
        )

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Event":
        return cls(
            id=str(value.get("id") or f"evt-{uuid.uuid4().hex}"),
            type=str(value.get("type") or ""),
            payload=dict(value.get("payload") or {}),
            created_at=float(value.get("created_at") or time.time()),
            processed=bool(value.get("processed", False)),
            processed_at=(
                float(value["processed_at"])
                if value.get("processed_at") is not None
                else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "payload": dict(self.payload),
            "created_at": float(self.created_at),
            "processed": bool(self.processed),
            "processed_at": self.processed_at,
        }
