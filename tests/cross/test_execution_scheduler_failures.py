from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from modules.execution.scheduler import ExecutionSchedule, ExecutionScheduler


class InMemoryStorage:
    def __init__(self) -> None:
        self._data: dict[str, dict[str, object]] = {}

    async def set(self, namespace: str, key: str, value: object) -> None:
        self._data.setdefault(namespace, {})[key] = value

    async def get(self, namespace: str, key: str):
        return self._data.get(namespace, {}).get(key)

    async def list_keys(self, namespace: str):
        return list(self._data.get(namespace, {}).keys())


class RaisingController:
    async def execute_operation(self, **kwargs):
        raise RuntimeError("scheduler execution failed")


@pytest.mark.asyncio
async def test_tick_does_not_mark_failed_run_as_success():
    runtime = SimpleNamespace(storage=InMemoryStorage())
    scheduler = ExecutionScheduler(runtime, RaisingController())

    now = datetime.now(UTC)
    sched = ExecutionSchedule(
        schedule_id="sched-failure",
        operation_type="test.failure",
        params={},
        context={},
        trigger_type="delay",
        trigger_at=now,
        trigger_every_seconds=None,
        trigger_cron=None,
        enabled=True,
        max_runs=None,
        run_count=0,
        last_run_at=None,
        next_run_at=now,
        created_at=now,
    )
    await scheduler.save_schedule(sched)

    await scheduler.tick(now=now)

    stored = await runtime.storage.get("execution", "schedules/sched-failure")
    assert stored["run_count"] == 0
    assert stored["enabled"] is True
    assert stored["last_run_at"] is None
