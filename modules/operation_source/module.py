from __future__ import annotations

import time
from typing import Any

from core.operations.models import Operation


class DefaultOperationSource:
    def __init__(self, storage: Any, *, limit: int = 1000, max_runnable: int = 100) -> None:
        self.storage = storage
        self.limit = int(limit)
        self.max_runnable = int(max_runnable)

    @staticmethod
    def _status_value(operation: Operation) -> str:
        status = getattr(operation, "status", None)
        return getattr(status, "value", status) or ""

    @staticmethod
    def _is_failed_retry_due(operation: Operation, now: float) -> bool:
        retry_count = int(getattr(operation, "retry_count", 0) or 0)
        max_retries = int(getattr(operation, "max_retries", 0) or 0)
        next_retry_at = getattr(operation, "next_retry_at", None)
        if retry_count >= max_retries:
            return False
        if next_retry_at is None:
            return True
        try:
            return now >= float(next_retry_at)
        except (TypeError, ValueError):
            return False

    async def get_runnable(self) -> list[Operation]:
        now = time.time()

        created_ops = await self.storage.list(limit=self.limit, status="created")
        failed_ops = await self.storage.list(limit=self.limit, status="failed")

        runnable: list[Operation] = list(created_ops)
        for operation in failed_ops:
            if self._status_value(operation) == "failed" and self._is_failed_retry_due(operation, now):
                runnable.append(operation)

        runnable.sort(key=lambda operation: getattr(operation, "priority", 0) or 0)
        return runnable[: self.max_runnable]
