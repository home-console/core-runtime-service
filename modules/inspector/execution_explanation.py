"""Read-only execution explanation layer for the inspector boundary.

This module is intentionally separated from `core/execution`.
It reads operations, attempts, and execution traces, then derives the WHY:
root cause, retryability, severity, and story blocks.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Protocol

from core.operations.models import Attempt, Operation
import logging
logger = logging.getLogger(__name__)


class ExplanationSeverity(str, Enum):
    info = "info"
    warning = "warning"
    error = "error"
    critical = "critical"


class FailureType(str, Enum):
    none = "none"
    timeout = "timeout"
    cancelled = "cancelled"
    lost_claim = "lost_claim"
    transient = "transient"
    terminal = "terminal"
    unknown = "unknown"


class RetryDecision(str, Enum):
    not_retryable = "not_retryable"
    retryable = "retryable"
    retry_scheduled = "retry_scheduled"
    retry_exhausted = "retry_exhausted"
    unknown = "unknown"


class StoryBlockKind(str, Enum):
    ATTEMPT = "ATTEMPT"
    RETRY = "RETRY"
    FINAL_RESULT = "FINAL RESULT"


class CauseType(str, Enum):
    success = "success"
    timeout = "timeout"
    cancelled = "cancelled"
    lost_claim = "lost_claim"
    retryable_failure = "retryable_failure"
    terminal_failure = "terminal_failure"
    retry_trigger = "retry_trigger"
    manual_trigger = "manual_trigger"
    automatic_trigger = "automatic_trigger"
    unknown = "unknown"


def _get_value(source: Any, key: str, default: Any = None) -> Any:
    if source is None:
        return default
    if isinstance(source, Mapping):
        return source.get(key, default)
    return getattr(source, key, default)


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "value") and not isinstance(value, (str, bytes)):
        value = getattr(value, "value")
    return str(value).strip().lower()


def _clamp_confidence(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _as_tuple(value: Optional[Sequence[Any]]) -> tuple[Any, ...]:
    if value is None:
        return ()
    return tuple(value)


def _extract_error_fields(source: Any) -> tuple[Optional[str], Optional[str]]:
    error = _get_value(source, "error")
    if isinstance(error, Mapping):
        code = error.get("code") or _get_value(source, "error_code")
        message = error.get("message") or _get_value(source, "error_message")
        return (
            str(code) if code is not None else None,
            str(message) if message is not None else None,
        )
    code = _get_value(source, "error_code")
    message = _get_value(source, "error_message")
    if error is not None and hasattr(error, "code"):
        code = getattr(error, "code", code)
    if error is not None and hasattr(error, "message"):
        message = getattr(error, "message", message)
    return (
        str(code) if code is not None else None,
        str(message) if message is not None else None,
    )


@dataclass(frozen=True)
class InferredCause:
    code: CauseType
    summary: str
    confidence: float
    severity: ExplanationSeverity
    fallback: bool = False
    evidence: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "summary": self.summary,
            "confidence": self.confidence,
            "severity": self.severity.value,
            "fallback": self.fallback,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class TimelineEvent:
    kind: str
    attempt_index: Optional[int] = None
    attempt_id: Optional[str] = None
    at: Optional[Any] = None
    status: Optional[str] = None
    message: Optional[str] = None
    detail: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "attempt_index": self.attempt_index,
            "attempt_id": self.attempt_id,
            "at": self.at,
            "status": self.status,
            "message": self.message,
            "detail": self.detail,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class StoryBlock:
    kind: StoryBlockKind
    events: tuple[TimelineEvent, ...]
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "summary": self.summary,
            "events": [event.to_dict() for event in self.events],
        }


@dataclass(frozen=True)
class AttemptExplanation:
    attempt_id: str
    attempt_index: int
    status: str
    cause: InferredCause
    confidence: float
    severity: ExplanationSeverity
    retry_reason: Optional[InferredCause] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "attempt_index": self.attempt_index,
            "status": self.status,
            "cause": self.cause.to_dict(),
            "confidence": self.confidence,
            "severity": self.severity.value,
            "retry_reason": self.retry_reason.to_dict() if self.retry_reason else None,
        }


@dataclass(frozen=True)
class ExplanationContext:
    retry_decision: RetryDecision
    failure_type: FailureType
    timeout: bool
    cancelled: bool
    lost_claim: bool
    inferred_root_cause: InferredCause

    def to_dict(self) -> dict[str, Any]:
        return {
            "retry_decision": self.retry_decision.value,
            "failure_type": self.failure_type.value,
            "timeout": self.timeout,
            "cancelled": self.cancelled,
            "lost_claim": self.lost_claim,
            "inferred_root_cause": self.inferred_root_cause.to_dict(),
        }


@dataclass(frozen=True)
class ExecutionView:
    operation: Operation
    attempts: tuple[Attempt, ...] = field(default_factory=tuple)
    timeline: tuple[TimelineEvent, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ExecutionExplanation:
    context: ExplanationContext
    operation: Operation
    attempts: tuple[AttemptExplanation, ...]
    story_blocks: tuple[StoryBlock, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "context": self.context.to_dict(),
            "operation": {
                "operation_id": self.operation.operation_id,
                "operation_type": self.operation.type,
                "status": self.operation.status.value,
            },
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "story_blocks": [block.to_dict() for block in self.story_blocks],
        }


class ExecutionExplanationSource(Protocol):
    async def get_operation(self, operation_id: str) -> Operation | None: ...

    async def get_attempts(self, operation_id: str) -> Sequence[Attempt]: ...

    async def get_timeline(self, operation_id: str) -> Sequence[TimelineEvent]: ...


class RuntimeExecutionExplanationSource:
    """Read-only source backed by a runtime object."""

    def __init__(self, runtime: Any):
        self._runtime = runtime

    async def get_operation(self, operation_id: str) -> Operation | None:
        operations = getattr(self._runtime, "operations", None)
        if operations is None or not hasattr(operations, "get"):
            return None
        return await operations.get(operation_id)

    async def get_attempts(self, operation_id: str) -> Sequence[Attempt]:
        operations = getattr(self._runtime, "operations", None)
        if operations is None or not hasattr(operations, "get_attempts"):
            return []
        return await operations.get_attempts(operation_id)

    async def get_timeline(self, operation_id: str) -> Sequence[TimelineEvent]:
        storage = getattr(self._runtime, "storage", None)
        if storage is None:
            return []

        events: list[TimelineEvent] = []

        try:
            keys = await storage.list_keys("execution")
        except Exception as e:
            logger.warning("execution_explanation.get_timeline: failed to list items: %s", e, exc_info=True)
            return []

        traces: list[dict[str, Any]] = []
        prefix = f"by_operation/{operation_id}/"
        for key in keys:
            if not key.startswith(prefix):
                continue
            try:
                idx = await storage.get("execution", key)
                if not isinstance(idx, dict):
                    continue
                execution_id = idx.get("execution_id")
                if not execution_id:
                    continue
                trace = await storage.get("execution", f"traces/{execution_id}")
                if isinstance(trace, dict):
                    traces.append(trace)
            except Exception:
                logger.debug("execution_explanation.get_timeline: error processing item (skipping)", exc_info=True)
                continue

        traces.sort(
            key=lambda item: (
                int(item.get("retry_index", 0) or 0),
                str(item.get("execution_id", "")),
            )
        )

        for trace in traces:
            retry_index = int(trace.get("retry_index", 0) or 0)
            execution_id = str(trace.get("execution_id", ""))
            started_at = trace.get("started_at")
            finished_at = trace.get("finished_at")
            status = trace.get("status")
            error_code = trace.get("error_code")
            error_message = trace.get("error_message")

            events.append(
                TimelineEvent(
                    kind="attempt_started",
                    attempt_index=retry_index,
                    attempt_id=execution_id,
                    at=started_at,
                    status="running",
                )
            )
            if trace.get("parent_execution_id"):
                events.append(
                    TimelineEvent(
                        kind="retry_requested",
                        attempt_index=retry_index,
                        attempt_id=execution_id,
                        at=started_at,
                        message="retry from parent execution",
                        detail=str(trace.get("parent_execution_id")),
                    )
                )
            events.append(
                TimelineEvent(
                    kind="attempt_finished",
                    attempt_index=retry_index,
                    attempt_id=execution_id,
                    at=finished_at,
                    status=status,
                    message=error_message,
                    detail=error_code,
                )
            )

        if traces:
            final = traces[-1]
            events.append(
                TimelineEvent(
                    kind="final_result",
                    attempt_index=int(final.get("retry_index", 0) or 0),
                    attempt_id=str(final.get("execution_id", "")),
                    at=final.get("finished_at"),
                    status=final.get("status"),
                    message=final.get("error_message"),
                    detail=final.get("error_code"),
                )
            )

        return events


_explanation_source: ExecutionExplanationSource | None = None


def configure_execution_explanation_source(
    source: ExecutionExplanationSource | None,
) -> None:
    global _explanation_source
    _explanation_source = source


def clear_execution_explanation_source() -> None:
    configure_execution_explanation_source(None)


def _require_source() -> ExecutionExplanationSource:
    if _explanation_source is None:
        raise RuntimeError(
            "Execution explanation source is not configured. "
            "Call configure_execution_explanation_source() first."
        )
    return _explanation_source


def _severity_for_failure(
    failure_type: FailureType, code: str | None = None
) -> ExplanationSeverity:
    if failure_type in (FailureType.timeout, FailureType.lost_claim):
        return ExplanationSeverity.warning
    if failure_type == FailureType.cancelled:
        return ExplanationSeverity.info
    if code in {
        "execution_error",
        "invalid_claim",
        "execution_limit_exceeded",
        "retry_limit_exceeded",
        "unknown_operation_type",
        "no_operations_manager",
    }:
        return ExplanationSeverity.critical
    if failure_type == FailureType.transient:
        return ExplanationSeverity.warning
    if failure_type == FailureType.terminal:
        return ExplanationSeverity.error
    return ExplanationSeverity.warning


def _failure_type_from_view(
    attempt: Any, operation: Any, timeline: Sequence[Any]
) -> FailureType:
    attempt_status = _normalize_text(_get_value(attempt, "status"))
    operation_status = _normalize_text(_get_value(operation, "status"))
    attempt_error_code, attempt_error_message = _extract_error_fields(attempt)
    operation_error_code, operation_error_message = _extract_error_fields(operation)
    error_code = _normalize_text(attempt_error_code or operation_error_code)
    error_message = _normalize_text(attempt_error_message or operation_error_message)
    cancel_requested = bool(_get_value(operation, "cancel_requested", False))

    if (
        attempt_status == "timeout"
        or error_code == "timeout"
        or "timed out" in error_message
    ):
        return FailureType.timeout
    if (
        attempt_status == "cancelled"
        or operation_status == "cancelled"
        or error_code == "cancelled"
        or cancel_requested
    ):
        return FailureType.cancelled
    if attempt_status == "lost_claim" or error_code == "lost_claim":
        return FailureType.lost_claim
    if error_code in {
        "timeout",
        "transient",
        "network",
        "device_offline",
        "integration_unavailable",
        "rate_limited",
        "lost_claim",
    }:
        return FailureType.transient
    if attempt_status in {"failed", "error"} or operation_status in {"failed", "error"}:
        if error_code or error_message:
            return FailureType.terminal
        return FailureType.unknown
    if attempt_status in {"completed", "ok", "success"} or operation_status in {
        "completed",
        "ok",
        "success",
    }:
        return FailureType.none
    if any(
        _normalize_text(_get_value(event, "kind"))
        in {"timeout", "cancelled", "lost_claim"}
        for event in timeline
    ):
        if any(
            _normalize_text(_get_value(event, "kind")) == "timeout"
            for event in timeline
        ):
            return FailureType.timeout
        if any(
            _normalize_text(_get_value(event, "kind")) == "cancelled"
            for event in timeline
        ):
            return FailureType.cancelled
        if any(
            _normalize_text(_get_value(event, "kind")) == "lost_claim"
            for event in timeline
        ):
            return FailureType.lost_claim
    return FailureType.unknown


def _collect_evidence(
    attempt: Any, operation: Any, timeline: Sequence[Any]
) -> tuple[str, ...]:
    evidence: list[str] = []
    attempt_id = _get_value(attempt, "attempt_id")
    attempt_index = _get_value(attempt, "attempt_index")
    attempt_error_code, attempt_error_message = _extract_error_fields(attempt)
    operation_error_code, operation_error_message = _extract_error_fields(operation)
    error_code = attempt_error_code or operation_error_code
    error_message = attempt_error_message or operation_error_message

    if attempt_id is not None:
        evidence.append(f"attempt_id={attempt_id}")
    if attempt_index is not None:
        evidence.append(f"attempt_index={attempt_index}")
    if error_code:
        evidence.append(f"error_code={error_code}")
    if error_message:
        evidence.append(f"error_message={error_message}")

    for event in timeline:
        if attempt_id is not None and _get_value(event, "attempt_id") == attempt_id:
            kind = _get_value(event, "kind")
            message = _get_value(event, "message")
            if kind:
                evidence.append(f"timeline.kind={kind}")
            if message:
                evidence.append(f"timeline.message={message}")
        elif (
            attempt_index is not None
            and _get_value(event, "attempt_index") == attempt_index
        ):
            kind = _get_value(event, "kind")
            if kind:
                evidence.append(f"timeline.kind={kind}")

    seen: set[str] = set()
    result: list[str] = []
    for item in evidence:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return tuple(result)


def infer_retry_reason(attempt: Any, operation: Any) -> InferredCause:
    explicit_retry_reason = _get_value(attempt, "retry_reason")
    attempt_status = _normalize_text(_get_value(attempt, "status"))
    attempt_error_code, _ = _extract_error_fields(attempt)
    operation_error_code, _ = _extract_error_fields(operation)
    error_code = _normalize_text(attempt_error_code or operation_error_code)
    max_retries = _get_value(operation, "max_retries")
    retry_count = int(_get_value(operation, "retry_count", 0) or 0)

    if explicit_retry_reason:
        return InferredCause(
            code=CauseType.retry_trigger,
            summary=str(explicit_retry_reason),
            confidence=0.96,
            severity=ExplanationSeverity.info,
            fallback=False,
            evidence=(f"retry_reason={explicit_retry_reason}",),
        )
    if attempt_status == "timeout" or error_code == "timeout":
        return InferredCause(
            CauseType.retryable_failure,
            "Retryable timeout",
            0.98,
            ExplanationSeverity.warning,
            False,
            ("timeout",),
        )
    if attempt_status == "lost_claim" or error_code == "lost_claim":
        return InferredCause(
            CauseType.retryable_failure,
            "Claim lease was lost during execution",
            0.97,
            ExplanationSeverity.warning,
            False,
            ("lost_claim",),
        )
    if (
        attempt_status == "cancelled"
        or error_code == "cancelled"
        or bool(_get_value(operation, "cancel_requested", False))
    ):
        return InferredCause(
            CauseType.terminal_failure,
            "Cancelled execution is not retried automatically",
            0.92,
            ExplanationSeverity.info,
            False,
            ("cancelled",),
        )
    if error_code in {
        "timeout",
        "transient",
        "network",
        "device_offline",
        "integration_unavailable",
        "rate_limited",
        "lost_claim",
    }:
        return InferredCause(
            CauseType.retryable_failure,
            f"Retryable failure: {error_code}",
            0.9,
            ExplanationSeverity.warning,
            False,
            (f"error_code={error_code}",),
        )
    if max_retries is not None and retry_count >= int(max_retries):
        return InferredCause(
            CauseType.terminal_failure,
            "Retry budget exhausted",
            0.88,
            ExplanationSeverity.error,
            False,
            (f"retry_count={retry_count}", f"max_retries={max_retries}"),
        )
    if retry_count > 0:
        return InferredCause(
            CauseType.retry_trigger,
            "Execution is a retry of a previous attempt",
            0.8,
            ExplanationSeverity.info,
            True,
            (f"retry_count={retry_count}",),
        )
    return InferredCause(
        CauseType.unknown,
        "No explicit retry reason was recorded",
        0.35,
        ExplanationSeverity.info,
        True,
        (),
    )


def infer_trigger_reason(operation: Any) -> InferredCause:
    triggered_by = _normalize_text(_get_value(operation, "triggered_by"))
    parent_operation_id = _get_value(operation, "parent_operation_id")
    retry_count = int(_get_value(operation, "retry_count", 0) or 0)
    source_event = _get_value(operation, "source_event")
    causation_id = _get_value(operation, "causation_id")

    if parent_operation_id is not None or retry_count > 0:
        evidence = []
        if parent_operation_id is not None:
            evidence.append(f"parent_operation_id={parent_operation_id}")
        if retry_count > 0:
            evidence.append(f"retry_count={retry_count}")
        return InferredCause(
            CauseType.retry_trigger,
            "Triggered as a retry of a previous execution",
            0.94,
            ExplanationSeverity.info,
            False,
            tuple(evidence),
        )
    if triggered_by in {"manual", "admin"}:
        return InferredCause(
            CauseType.manual_trigger,
            "Triggered by a manual/admin action",
            0.96,
            ExplanationSeverity.info,
            False,
            (f"triggered_by={triggered_by}",),
        )
    if source_event is not None or causation_id is not None:
        evidence = []
        if source_event is not None:
            evidence.append(f"source_event={source_event}")
        if causation_id is not None:
            evidence.append(f"causation_id={causation_id}")
        return InferredCause(
            CauseType.automatic_trigger,
            "Triggered by an upstream event or system causation chain",
            0.82,
            ExplanationSeverity.info,
            False,
            tuple(evidence),
        )
    if triggered_by:
        return InferredCause(
            CauseType.automatic_trigger,
            f"Triggered by {triggered_by}",
            0.7,
            ExplanationSeverity.info,
            True,
            (f"triggered_by={triggered_by}",),
        )
    return InferredCause(
        CauseType.unknown,
        "Trigger reason is not recorded",
        0.3,
        ExplanationSeverity.info,
        True,
        (),
    )


def _is_final_result_event(event: Any) -> bool:
    kind = _normalize_text(_get_value(event, "kind"))
    status = _normalize_text(_get_value(event, "status"))
    return kind in {
        "final",
        "final_result",
        "result",
        "completed",
        "failed",
        "cancelled",
    } or status in {"completed", "failed", "error", "cancelled", "ok", "success"}


def _is_retry_event(event: Any) -> bool:
    kind = _normalize_text(_get_value(event, "kind"))
    message = _normalize_text(_get_value(event, "message"))
    return (
        kind in {"retry", "retry_requested", "retry_scheduled", "backoff"}
        or "retry" in message
    )


_STORY_SUMMARY_BY_KIND = {
    StoryBlockKind.ATTEMPT: "Attempt lifecycle",
    StoryBlockKind.RETRY: "Retry transition",
    StoryBlockKind.FINAL_RESULT: "Final result",
}


def group_timeline_into_blocks(timeline: Sequence[Any]) -> tuple[StoryBlock, ...]:
    if not timeline:
        return ()

    blocks: list[StoryBlock] = []
    current_events: list[TimelineEvent] = []
    current_kind: Optional[StoryBlockKind] = None

    def flush(next_kind: Optional[StoryBlockKind]) -> None:
        nonlocal current_events, current_kind
        if current_kind is not None and current_events:
            blocks.append(
                StoryBlock(
                    kind=current_kind,
                    events=tuple(current_events),
                    summary=_STORY_SUMMARY_BY_KIND[current_kind],
                )
            )
        current_events = []
        current_kind = next_kind

    for raw_event in timeline:
        event = (
            raw_event
            if isinstance(raw_event, TimelineEvent)
            else TimelineEvent(
                kind=str(_get_value(raw_event, "kind", "event")),
                attempt_index=_get_value(raw_event, "attempt_index"),
                attempt_id=_get_value(raw_event, "attempt_id"),
                at=_get_value(raw_event, "at"),
                status=_get_value(raw_event, "status"),
                message=_get_value(raw_event, "message"),
                detail=_get_value(raw_event, "detail"),
                metadata=_get_value(raw_event, "metadata", {}),
            )
        )

        if _is_retry_event(event):
            if current_kind != StoryBlockKind.RETRY:
                flush(StoryBlockKind.RETRY)
            current_events.append(event)
            continue
        if _is_final_result_event(event):
            if current_kind != StoryBlockKind.FINAL_RESULT:
                flush(StoryBlockKind.FINAL_RESULT)
            current_events.append(event)
            continue
        if current_kind != StoryBlockKind.ATTEMPT:
            flush(StoryBlockKind.ATTEMPT)
        current_events.append(event)

    if current_kind is not None and current_events:
        blocks.append(
            StoryBlock(
                kind=current_kind,
                events=tuple(current_events),
                summary=_STORY_SUMMARY_BY_KIND[current_kind],
            )
        )

    return tuple(blocks)


def _select_root_cause(
    attempt_explanations: Sequence[AttemptExplanation], operation: Any
) -> InferredCause:
    if attempt_explanations:
        pool = [
            item
            for item in attempt_explanations
            if item.cause.code != CauseType.success
        ]
        ranked = sorted(
            pool or list(attempt_explanations),
            key=lambda item: (
                1
                if item.severity
                in {ExplanationSeverity.error, ExplanationSeverity.critical}
                else 0,
                item.confidence,
                item.attempt_index,
            ),
            reverse=True,
        )
        return ranked[0].cause

    operation_status = _normalize_text(_get_value(operation, "status"))
    operation_error_code, operation_error_message = _extract_error_fields(operation)
    error_code = _normalize_text(operation_error_code)
    error_message = _normalize_text(operation_error_message)

    if operation_status in {"ok", "completed", "success"}:
        return InferredCause(
            CauseType.success,
            "Execution completed successfully",
            0.99,
            ExplanationSeverity.info,
            False,
            (f"status={operation_status}",),
        )
    if operation_status == "cancelled" or error_code == "cancelled":
        return InferredCause(
            CauseType.cancelled,
            "Execution was cancelled",
            0.95,
            ExplanationSeverity.info,
            False,
            ("cancelled",),
        )
    if (
        operation_status == "timeout"
        or error_code == "timeout"
        or "timed out" in error_message
    ):
        return InferredCause(
            CauseType.timeout,
            "Execution timed out",
            0.97,
            ExplanationSeverity.warning,
            False,
            ("timeout",),
        )
    return InferredCause(
        CauseType.unknown,
        "Root cause could not be inferred from the view",
        0.2,
        ExplanationSeverity.warning,
        True,
        (),
    )


def _build_retry_decision(
    operation: Any, root_cause: InferredCause, story_blocks: Sequence[StoryBlock]
) -> RetryDecision:
    status = _normalize_text(_get_value(operation, "status"))
    retry_count = int(_get_value(operation, "retry_count", 0) or 0)
    max_retries = _get_value(operation, "max_retries")
    next_retry_at = _get_value(operation, "next_retry_at")

    if status in {"ok", "completed", "success"}:
        return RetryDecision.not_retryable
    if root_cause.code == CauseType.cancelled:
        return RetryDecision.not_retryable
    if max_retries is not None and retry_count >= int(max_retries):
        return RetryDecision.retry_exhausted
    if (
        any(block.kind == StoryBlockKind.RETRY for block in story_blocks)
        or next_retry_at is not None
    ):
        return RetryDecision.retry_scheduled
    if root_cause.code in {
        CauseType.timeout,
        CauseType.lost_claim,
        CauseType.retryable_failure,
    }:
        return RetryDecision.retryable
    if status in {"failed", "error"}:
        return (
            RetryDecision.retryable
            if root_cause.code != CauseType.terminal_failure
            else RetryDecision.not_retryable
        )
    return RetryDecision.unknown


def infer_attempt_cause(
    attempt: Any, operation: Any, timeline: Sequence[Any]
) -> AttemptExplanation:
    failure_type = _failure_type_from_view(attempt, operation, timeline)
    attempt_error_code, attempt_error_message = _extract_error_fields(attempt)
    operation_error_code, operation_error_message = _extract_error_fields(operation)
    error_code = _normalize_text(attempt_error_code or operation_error_code)
    error_message = _normalize_text(attempt_error_message or operation_error_message)
    evidence = _collect_evidence(attempt, operation, timeline)

    if failure_type == FailureType.none:
        cause = InferredCause(
            CauseType.success,
            "Execution finished successfully",
            0.99,
            ExplanationSeverity.info,
            False,
            evidence,
        )
    elif failure_type == FailureType.timeout:
        cause = InferredCause(
            CauseType.timeout,
            "Execution exceeded the configured timeout",
            0.98 if error_code == "timeout" else 0.9,
            ExplanationSeverity.warning,
            False,
            evidence,
        )
    elif failure_type == FailureType.cancelled:
        cause = InferredCause(
            CauseType.cancelled,
            "Execution was cancelled",
            0.96 if _get_value(operation, "cancel_requested", False) else 0.9,
            ExplanationSeverity.info,
            False,
            evidence,
        )
    elif failure_type == FailureType.lost_claim:
        cause = InferredCause(
            CauseType.lost_claim,
            "The claim lease was lost before execution could finish",
            0.97,
            ExplanationSeverity.warning,
            False,
            evidence,
        )
    elif failure_type == FailureType.transient:
        cause = InferredCause(
            CauseType.retryable_failure,
            "A transient failure interrupted the attempt",
            0.82,
            _severity_for_failure(failure_type, error_code),
            False,
            evidence,
        )
    elif failure_type == FailureType.terminal:
        cause = InferredCause(
            CauseType.terminal_failure,
            "The attempt failed for a terminal reason",
            0.8 if error_code else 0.6,
            _severity_for_failure(failure_type, error_code),
            False,
            evidence,
        )
    else:
        cause = InferredCause(
            CauseType.unknown,
            "No explicit cause could be inferred",
            0.45 if (error_code or error_message) else 0.25,
            ExplanationSeverity.warning,
            True,
            evidence,
        )

    retry_reason = infer_retry_reason(attempt, operation)
    return AttemptExplanation(
        attempt_id=str(_get_value(attempt, "attempt_id", "")),
        attempt_index=int(_get_value(attempt, "attempt_index", 0) or 0),
        status=str(_get_value(attempt, "status", "unknown")),
        cause=cause,
        confidence=_clamp_confidence(max(cause.confidence, retry_reason.confidence)),
        severity=cause.severity,
        retry_reason=retry_reason,
    )


def build_execution_explanation_from_view(
    view: ExecutionView | Any,
) -> ExecutionExplanation:
    operation = _get_value(view, "operation")
    attempts = _as_tuple(_get_value(view, "attempts", ()))
    timeline = _as_tuple(_get_value(view, "timeline", ()))

    attempt_explanations = tuple(
        infer_attempt_cause(attempt, operation, timeline) for attempt in attempts
    )
    story_blocks = group_timeline_into_blocks(timeline)
    root_cause = _select_root_cause(attempt_explanations, operation)
    failure_type = _failure_type_from_view(
        attempts[-1] if attempts else operation, operation, timeline
    )
    retry_decision = _build_retry_decision(operation, root_cause, story_blocks)

    context = ExplanationContext(
        retry_decision=retry_decision,
        failure_type=failure_type,
        timeout=failure_type == FailureType.timeout,
        cancelled=failure_type == FailureType.cancelled,
        lost_claim=failure_type == FailureType.lost_claim,
        inferred_root_cause=root_cause,
    )

    return ExecutionExplanation(
        context=context,
        operation=operation,
        attempts=attempt_explanations,
        story_blocks=story_blocks,
    )


async def build_execution_explanation(operation_id: str) -> ExecutionExplanation:
    source = _require_source()
    operation = await source.get_operation(operation_id)
    if operation is None:
        raise ValueError(f"Operation not found: {operation_id}")

    attempts = tuple(await source.get_attempts(operation_id))
    timeline = tuple(await source.get_timeline(operation_id))
    view = ExecutionView(operation=operation, attempts=attempts, timeline=timeline)
    return build_execution_explanation_from_view(view)
