import pytest
from core.operations.models import (
    Attempt,
    AttemptStatus,
    Operation,
    OperationError,
    OperationInitiator,
    OperationInitiatorKind,
    OperationStatus,
)
from modules.inspector.execution_explanation import (
    CauseType,
    ExecutionView,
    ExplanationSeverity,
    FailureType,
    RetryDecision,
    StoryBlockKind,
    TimelineEvent,
    build_execution_explanation,
    build_execution_explanation_from_view,
    clear_execution_explanation_source,
    configure_execution_explanation_source,
    group_timeline_into_blocks,
    infer_attempt_cause,
    infer_retry_reason,
    infer_trigger_reason,
)


class FakeSource:
    def __init__(
        self,
        operation: Operation,
        attempts: tuple[Attempt, ...],
        timeline: tuple[TimelineEvent, ...],
    ):
        self._operation = operation
        self._attempts = attempts
        self._timeline = timeline

    async def get_operation(self, operation_id: str):
        return self._operation if operation_id == self._operation.operation_id else None

    async def get_attempts(self, operation_id: str):
        return self._attempts if operation_id == self._operation.operation_id else []

    async def get_timeline(self, operation_id: str):
        return self._timeline if operation_id == self._operation.operation_id else []


def _timeout_view() -> tuple[Operation, Attempt, tuple[TimelineEvent, ...]]:
    operation = Operation(
        operation_id="op-1",
        op_type="test.ping",
        params={},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
        retry_count=1,
        max_retries=3,
        triggered_by="system",
    )
    operation.status = OperationStatus.FAILED
    operation.error = OperationError(code="timeout", message="execution timeout")
    attempt = Attempt(
        attempt_id="att-1",
        operation_id="op-1",
        attempt_index=0,
        status=AttemptStatus.TIMEOUT,
        error={"code": "timeout", "message": "execution timeout"},
    )
    timeline = (
        TimelineEvent(kind="attempt_started", attempt_id="att-1", attempt_index=0),
        TimelineEvent(
            kind="attempt_finished",
            attempt_id="att-1",
            attempt_index=0,
            status="timeout",
        ),
        TimelineEvent(
            kind="retry_scheduled",
            attempt_id="att-1",
            attempt_index=0,
            message="retry after timeout",
        ),
    )
    return operation, attempt, timeline


def test_infer_attempt_cause_timeout_marks_warning_and_retryable_reason():
    operation, attempt, timeline = _timeout_view()

    explanation = infer_attempt_cause(attempt, operation, timeline)

    assert explanation.cause.code == CauseType.timeout
    assert explanation.cause.severity == ExplanationSeverity.warning
    assert explanation.cause.confidence >= 0.95
    assert explanation.retry_reason is not None
    assert explanation.retry_reason.code == CauseType.retryable_failure


def test_infer_attempt_cause_cancel_is_info_and_not_retryable():
    operation = Operation(
        operation_id="op-2",
        op_type="test.cancel",
        params={},
        initiator=OperationInitiator(kind=OperationInitiatorKind.ADMIN),
        triggered_by="admin",
        cancel_requested=True,
    )
    operation.status = OperationStatus.CANCELLED
    operation.error = None
    attempt = Attempt(
        attempt_id="att-2",
        operation_id="op-2",
        attempt_index=0,
        status=AttemptStatus.CANCELLED,
        error={"code": "cancelled", "message": "execution cancelled"},
    )

    explanation = infer_attempt_cause(attempt, operation, ())

    assert explanation.cause.code == CauseType.cancelled
    assert explanation.cause.severity == ExplanationSeverity.info
    assert explanation.retry_reason is not None
    assert explanation.retry_reason.code == CauseType.terminal_failure


def test_infer_attempt_cause_lost_claim_marks_warning():
    operation = Operation(
        operation_id="op-3",
        op_type="test.claim",
        params={},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
    )
    operation.status = OperationStatus.FAILED
    attempt = Attempt(
        attempt_id="att-3",
        operation_id="op-3",
        attempt_index=0,
        status=AttemptStatus.LOST_CLAIM,
        error={"code": "lost_claim", "message": "claim lease couldn't be extended"},
    )

    explanation = infer_attempt_cause(attempt, operation, ())

    assert explanation.cause.code == CauseType.lost_claim
    assert explanation.cause.severity == ExplanationSeverity.warning
    assert explanation.retry_reason is not None
    assert explanation.retry_reason.code == CauseType.retryable_failure


def test_infer_attempt_cause_unknown_falls_back():
    operation = Operation(
        operation_id="op-4",
        op_type="test.unknown",
        params={},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
    )
    operation.status = OperationStatus.FAILED
    attempt = Attempt(
        attempt_id="att-4",
        operation_id="op-4",
        attempt_index=0,
        status=AttemptStatus.FAILED,
    )

    explanation = infer_attempt_cause(attempt, operation, ())

    assert explanation.cause.code == CauseType.unknown
    assert explanation.cause.fallback is True
    assert explanation.confidence < 0.5


def test_group_timeline_into_blocks_splits_attempt_retry_final():
    timeline = (
        TimelineEvent(kind="attempt_started", attempt_id="att-1", attempt_index=0),
        TimelineEvent(
            kind="attempt_finished",
            attempt_id="att-1",
            attempt_index=0,
            status="timeout",
        ),
        TimelineEvent(
            kind="retry_requested", attempt_id="att-1", attempt_index=0, message="retry"
        ),
        TimelineEvent(kind="attempt_started", attempt_id="att-2", attempt_index=1),
        TimelineEvent(
            kind="attempt_finished", attempt_id="att-2", attempt_index=1, status="ok"
        ),
        TimelineEvent(
            kind="final_result", attempt_id="att-2", attempt_index=1, status="ok"
        ),
    )

    blocks = group_timeline_into_blocks(timeline)

    assert [block.kind for block in blocks] == [
        StoryBlockKind.ATTEMPT,
        StoryBlockKind.RETRY,
        StoryBlockKind.ATTEMPT,
        StoryBlockKind.FINAL_RESULT,
    ]


def test_build_execution_explanation_combines_context_and_blocks():
    operation, attempt, timeline = _timeout_view()
    view = ExecutionView(operation=operation, attempts=(attempt,), timeline=timeline)

    explanation = build_execution_explanation_from_view(view)

    assert explanation.context.failure_type == FailureType.timeout
    assert explanation.context.retry_decision == RetryDecision.retry_scheduled
    assert explanation.context.inferred_root_cause.code == CauseType.timeout
    assert explanation.attempts[0].cause.code == CauseType.timeout
    assert explanation.story_blocks


def test_infer_trigger_reason_understands_retry_and_manual_signals():
    retry_operation = Operation(
        operation_id="op-5",
        op_type="test.retry",
        params={},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
        parent_operation_id="op-parent",
        retry_count=2,
    )
    retry_operation.status = OperationStatus.FAILED
    manual_operation = Operation(
        operation_id="op-6",
        op_type="test.manual",
        params={},
        initiator=OperationInitiator(kind=OperationInitiatorKind.ADMIN),
        triggered_by="manual",
    )

    retry_reason = infer_trigger_reason(retry_operation)
    manual_reason = infer_trigger_reason(manual_operation)

    assert retry_reason.code == CauseType.retry_trigger
    assert manual_reason.code == CauseType.manual_trigger


def test_infer_retry_reason_respects_retry_budget_exhaustion():
    operation = Operation(
        operation_id="op-7",
        op_type="test.retry-budget",
        params={},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
        retry_count=3,
        max_retries=3,
    )
    operation.status = OperationStatus.FAILED
    attempt = Attempt(
        attempt_id="att-7",
        operation_id="op-7",
        attempt_index=2,
        status=AttemptStatus.FAILED,
    )

    retry_reason = infer_retry_reason(attempt, operation)

    assert retry_reason.code == CauseType.terminal_failure
    assert retry_reason.summary == "Retry budget exhausted"


@pytest.mark.asyncio
async def test_build_execution_explanation_by_operation_id_uses_configured_source():
    operation, attempt, timeline = _timeout_view()
    configure_execution_explanation_source(FakeSource(operation, (attempt,), timeline))
    try:
        explanation = await build_execution_explanation("op-1")
    finally:
        clear_execution_explanation_source()

    assert explanation.operation.operation_id == "op-1"
    assert explanation.context.failure_type == FailureType.timeout
