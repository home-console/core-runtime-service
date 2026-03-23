# Execution Explanation Layer

Location: [modules/inspector/execution_explanation.py](modules/inspector/execution_explanation.py)

This layer is read-only. It derives "why" from the existing execution view and does not:

- change runtime behavior
- add storage tables
- depend on worker internals
- infer anything outside the `ExecutionView`

## Structures

### `ExecutionView`

Input aggregate for inference.

- `operation`: execution-level metadata
- `attempts`: attempt snapshots
- `timeline`: chronological events

## Final API

- `async build_execution_explanation(operation_id) -> ExecutionExplanation`
- `build_execution_explanation_from_view(view) -> ExecutionExplanation` for pure inference over a prebuilt read model

### `ExplanationContext`

Aggregates the explanation of the execution as a whole.

- `retry_decision`
- `failure_type`
- `timeout` / `cancelled` / `lost_claim`
- `inferred_root_cause`

### `AttemptExplanation`

Attempt-level explanation with:

- `cause`
- `confidence` in `[0..1]`
- `severity`

### `StoryBlock`

Timeline grouping into logical blocks:

- `ATTEMPT`
- `RETRY`
- `FINAL RESULT`

## Inference Rules

1. Explicit signals win.
- `timeout` in status/error code becomes `timeout` with high confidence.
- `cancelled` or `cancel_requested` becomes `cancelled`.
- `lost_claim` becomes `lost_claim`.

2. Retryable failures are classified before terminal fallbacks.
- `timeout`
- `lost_claim`
- retryable error codes like `transient`, `network`, `rate_limited`

3. When the cause is not clear, the layer falls back to `unknown`.
- confidence is low
- severity stays non-fatal unless the view explicitly says otherwise

4. Trigger inference is separate from failure inference.
- manual/admin action -> `manual_trigger`
- parent/retry metadata -> `retry_trigger`
- upstream event metadata -> `automatic_trigger`

## Severity Model

- `info`: normal completion, manual cancellation, retry trigger metadata
- `warning`: timeout, lost claim, retryable transient failures
- `error`: terminal execution failures and exhausted retry budgets
- `critical`: invariant-like conditions such as invalid claim / execution limit violations

## Examples

### Timeout

- attempt status: `timeout`
- error code: `timeout`
- result: cause = `timeout`, confidence close to `1.0`, severity = `warning`
- retry decision: usually `retryable` or `retry_scheduled`

### Cancel

- operation has `cancel_requested = true`
- result: cause = `cancelled`, severity = `info`
- retry decision: `not_retryable`

### Lost Claim

- attempt status: `lost_claim`
- result: cause = `lost_claim`, severity = `warning`
- retry decision: `retryable`

### Retry

- timeline has a `RETRY` block
- parent/retry metadata present
- root cause stays on the original failure, but the story shows the retry transition explicitly

## Boundaries

- `core/execution` no longer imports the explanation layer
- inference reads only `Operation`, `Attempt`, and execution trace snapshots
- the module does not mutate state
