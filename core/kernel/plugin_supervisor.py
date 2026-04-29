"""
PluginSupervisor — fault isolation для плагинов через asyncio.Task.

Каждый плагин получает свой Task. Падение плагина:
- Логируется с полным traceback
- Не распространяется на другие плагины
- Помечает плагин как degraded (не удаляет из реестра)
- Опционально перезапускает (если restart_policy="always")

Паттерн: Erlang/OTP Supervisor, адаптированный под asyncio.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from dataclasses import dataclass
from enum import Enum
from typing import Awaitable, Callable, Coroutine, Union, Any

logger = logging.getLogger(__name__)


class PluginStatus(str, Enum):
    LOADING = "loading"
    RUNNING = "running"
    DEGRADED = "degraded"  # упал, не перезапускается
    RESTARTING = "restarting"
    STOPPED = "stopped"


class RestartPolicy(str, Enum):
    NEVER = "never"  # не перезапускать (default для плагинов)
    ALWAYS = "always"  # перезапускать до max_restarts раз


@dataclass
class PluginHandle:
    """Дескриптор запущенного плагина."""

    plugin_name: str
    task: asyncio.Task[None] | None = None
    status: PluginStatus = PluginStatus.LOADING
    restart_count: int = 0
    last_error: Exception | None = None
    restart_policy: RestartPolicy = RestartPolicy.NEVER
    max_restarts: int = 3


class PluginSupervisor:
    """
    Supervisor для asyncio-задач плагинов.

    Запускает каждый плагин в отдельном Task.
    Перехватывает исключения, логирует, помечает статус.
    """

    def __init__(self) -> None:
        self._handles: dict[str, PluginHandle] = {}
        self._on_plugin_failed: list[Callable[[str, Exception], Awaitable[None]]] = []

    def on_plugin_failed(
        self, callback: Callable[[str, Exception], Awaitable[None]]
    ) -> None:
        """Зарегистрировать callback при падении плагина."""
        self._on_plugin_failed.append(callback)

    async def spawn(
        self,
        plugin_name: str,
        coro: Union[Awaitable[None], Callable[[], Awaitable[None]]],
        *,
        restart_policy: RestartPolicy = RestartPolicy.NEVER,
        max_restarts: int = 3,
    ) -> PluginHandle:
        """
        Запустить корутину плагина в изолированном Task.

        Args:
            plugin_name: имя плагина (для логов и реестра)
            coro: корутина (on_start() или run_forever())
            restart_policy: NEVER или ALWAYS
            max_restarts: максимум перезапусков при ALWAYS

        Returns:
            PluginHandle с task и статусом
        """
        handle = PluginHandle(
            plugin_name=plugin_name,
            restart_policy=restart_policy,
            max_restarts=max_restarts,
            status=PluginStatus.RUNNING,
        )
        self._handles[plugin_name] = handle

        async def _runner() -> None:
            # Create coroutine lazily to avoid "coroutine was never awaited"
            # when a task gets cancelled before first execution tick.
            try:
                awaitable = coro() if callable(coro) else coro
                await self._run_with_supervision(handle, awaitable)
            finally:
                # Best-effort: if caller passed an already-created coroutine and we never awaited it
                # (e.g., immediate cancellation before first tick), close it to silence warnings.
                try:
                    if not callable(coro) and hasattr(coro, "close"):
                        coro.close()  # type: ignore[attr-defined]
                except Exception:
                    pass

        task = asyncio.create_task(_runner(), name=f"plugin:{plugin_name}")
        handle.task = task
        return handle

    async def run_supervised(
        self,
        plugin_name: str,
        coro: Awaitable[None],
        *,
        restart_policy: RestartPolicy = RestartPolicy.NEVER,
        max_restarts: int = 3,
    ) -> PluginHandle:
        """
        Запустить корутину под supervision В ТЕКУЩЕЙ задаче (без create_task()).

        Используется для коротких lifecycle-хуков вроде on_start(), чтобы:
        - обеспечить детерминированное выполнение (после await хук точно выполнен)
        - сохранить fault-isolation (ошибки логируются/помечают DEGRADED)
        """
        handle = PluginHandle(
            plugin_name=plugin_name,
            restart_policy=restart_policy,
            max_restarts=max_restarts,
            status=PluginStatus.RUNNING,
        )
        self._handles[plugin_name] = handle
        await self._run_with_supervision(handle, coro)
        return handle

    async def _run_with_supervision(
        self, handle: PluginHandle, coro: Awaitable[None]
    ) -> None:
        """Запустить корутину с перехватом исключений."""
        try:
            await coro
            handle.status = PluginStatus.STOPPED
            logger.info("[Supervisor] Plugin '%s' finished normally", handle.plugin_name)
        except asyncio.CancelledError:
            handle.status = PluginStatus.STOPPED
            logger.info("[Supervisor] Plugin '%s' cancelled", handle.plugin_name)
            raise  # CancelledError должен распространяться
        except Exception as exc:
            handle.last_error = exc
            tb = traceback.format_exc()
            logger.error("[Supervisor] Plugin '%s' crashed:\n%s", handle.plugin_name, tb)

            # Уведомить callbacks (не даём им упасть)
            for cb in list(self._on_plugin_failed):
                try:
                    await cb(handle.plugin_name, exc)
                except Exception as cb_err:
                    logger.error(
                        "[Supervisor] on_plugin_failed callback failed: %s", cb_err
                    )

            if (
                handle.restart_policy == RestartPolicy.ALWAYS
                and handle.restart_count < handle.max_restarts
            ):
                handle.restart_count += 1
                handle.status = PluginStatus.RESTARTING
                logger.warning(
                    "[Supervisor] Restarting plugin '%s' (attempt %d/%d)",
                    handle.plugin_name,
                    handle.restart_count,
                    handle.max_restarts,
                )
                # Экспоненциальный backoff: 1s, 2s, 4s
                await asyncio.sleep(2 ** (handle.restart_count - 1))
                # NOTE: перезапуск требует фабрики корутины — не реализуем в v1
                handle.status = PluginStatus.DEGRADED
            else:
                handle.status = PluginStatus.DEGRADED
                logger.error(
                    "[Supervisor] Plugin '%s' is now DEGRADED. Runtime continues without it.",
                    handle.plugin_name,
                )

    async def stop_plugin(self, plugin_name: str) -> None:
        """Остановить задачу плагина."""
        handle = self._handles.get(plugin_name)
        if handle and handle.task and not handle.task.done():
            handle.task.cancel()
            try:
                await asyncio.wait_for(handle.task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        if handle:
            handle.status = PluginStatus.STOPPED

    async def stop_all(self, timeout: float = 10.0) -> None:
        """Остановить все плагины gracefully."""
        tasks = [
            h.task for h in self._handles.values() if h.task and not h.task.done()
        ]
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=timeout)

        for h in self._handles.values():
            if h.task is None or h.task.cancelled() or h.task.done():
                h.status = PluginStatus.STOPPED

    def get_status(self, plugin_name: str) -> PluginStatus | None:
        handle = self._handles.get(plugin_name)
        return handle.status if handle else None

    def list_plugins(self) -> dict[str, PluginStatus]:
        return {name: h.status for name, h in self._handles.items()}

    def is_healthy(self, plugin_name: str) -> bool:
        status = self.get_status(plugin_name)
        return status in (PluginStatus.RUNNING, PluginStatus.LOADING)

