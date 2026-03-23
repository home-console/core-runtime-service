from __future__ import annotations

import time
from typing import Any

from core.operations.models import Operation, OperationStatus

RETRYABLE_ERROR_CODES: set[str] = {
    "timeout",
    "transient",
    "network",
    "device_offline",
    "integration_unavailable",
    "rate_limited",
}


def is_retryable_error_code(code: Any) -> bool:
    if code is None:
        return False
    return str(code) in RETRYABLE_ERROR_CODES


def can_schedule_retry(operation: Operation) -> bool:
    if operation.status != OperationStatus.FAILED:
        return False
    if operation.error is None:
        return False
    if not is_retryable_error_code(operation.error.code):
        return False
    if int(operation.retry_count or 0) >= int(operation.max_retries or 0):
        return False
    return True


def is_retry_due(operation: Operation, now: float | None = None) -> bool:
    if not can_schedule_retry(operation):
        return False
    current = time.time() if now is None else float(now)
    if operation.next_retry_at is None:
        return True
    return current >= float(operation.next_retry_at)


def compute_next_retry_at(operation: Operation, now: float | None = None) -> float:
    current = time.time() if now is None else float(now)
    retry_count = int(operation.retry_count or 0)
    return current + float(2**retry_count)
