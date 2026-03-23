import asyncio
import time
from typing import Any

from core.operations.models import OperationStatus


class OperationWorker:
    def __init__(self, runtime: Any):
        self.runtime = runtime
        self.running = False
        self._task: asyncio.Task | None = None

    async def start(self):
        self.running = True
        if self._task is None:
            self._task = asyncio.current_task()
        try:
            while self.running:
                await self.tick()
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        finally:
            self.running = False

    async def stop(self) -> None:
        self.running = False
        if self._task is None or self._task is asyncio.current_task():
            return
        if not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def tick(self):
        now = time.time()

        created_ops = await self.runtime.operations.list(limit=1000, status="created")
        failed_ops = await self.runtime.operations.list(limit=1000, status="failed")

        ops = list(created_ops) + list(failed_ops)

        for op in ops:
            if op.status == OperationStatus.CREATED:
                if op.next_retry_at and now < op.next_retry_at:
                    continue
                await self.runtime.operations.execute(op)
                continue

            if op.status == OperationStatus.FAILED and op.can_retry(now):
                await self.runtime.operations.execute(op)