"""
RuntimeLifecycleMixin — lifecycle management для CoreRuntime.

Содержит:
- start / stop / shutdown / run
- _hydrate_critical_state
- _run_transports / _iter_transport_runners
- health_check / get_metrics
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Dict, Optional, cast

from core.dependency.models import RuntimeIntegrityError
from core.logger_helper import info, warning


class RuntimeLifecycleMixin:
    """Lifecycle management: start, stop, shutdown, health, metrics."""

    # Объявления атрибутов, которые предоставляет CoreRuntime.__init__.
    # Нужны для статического анализа (Pyright/mypy).
    _config: Any
    _running: bool
    _start_time: Optional[float]
    _worker_task: Optional[asyncio.Task]  # type: ignore[type-arg]
    critical_state_prefixes: list[str]
    dependency_resolver: Any
    event_bus: Any
    event_validation_middleware_factory: Any
    module_manager: Any
    plugin_manager: Any
    runtime_health_check: Any
    runtime_metrics_collector: Any
    service_registry: Any
    state_engine: Any
    storage: Any
    worker: Any

    def _iter_transport_runners(
        self,
    ) -> list[tuple[str, Callable[[Any], Awaitable[Any]]]]:
        """
        Найти transport runner'ы среди зарегистрированных модулей.

        Контракт: модуль экспортирует `run_transport(runtime)`.
        """
        runners: list[tuple[str, Callable[[Any], Awaitable[Any]]]] = []
        for module_name in self.module_manager.list_modules():
            module = self.module_manager.get_module(module_name)
            if module is None:
                continue
            run_transport = getattr(module, "run_transport", None)
            if callable(run_transport):
                runners.append(
                    (module_name, cast(Callable[[Any], Awaitable[Any]], run_transport))
                )
        return runners

    async def _run_transports(self) -> None:
        """Запустить transport runner'ы модулей."""
        runners = self._iter_transport_runners()
        if not runners:
            await info(
                self, "RUNTIME: no transport runners registered", component="runtime"
            )
            return

        for module_name, runner in runners:
            try:
                await info(
                    self,
                    f"RUNTIME: running transport for module '{module_name}'",
                    component="runtime",
                )
                await runner(self)
                await info(
                    self,
                    f"RUNTIME: transport runner for '{module_name}' returned",
                    component="runtime",
                )
            except Exception as e:
                await warning(
                    self,
                    f"Ошибка transport runner '{module_name}': {e}",
                    component="runtime",
                )
                import traceback

                traceback.print_exc()

    async def run(self) -> None:
        """
        Верный запуск: start (модули + плагины), затем transport runner'ы модулей.
        """
        await info(self, "RUNTIME: start() about to run", component="runtime")
        await self.start()
        await info(self, "RUNTIME: start() finished", component="runtime")

        await info(self, "RUNTIME: about to run transport runners", component="runtime")
        await self._run_transports()
        await info(self, "RUNTIME: transport runners finished", component="runtime")
        try:
            timeout = (
                getattr(self._config, "shutdown_timeout", 10) if self._config else 10
            )
            await asyncio.wait_for(self.shutdown(), timeout=timeout)
        except asyncio.TimeoutError:
            await warning(self, "Таймаут при остановке", component="runtime")

    async def _hydrate_critical_state(self) -> None:
        """
        Гидратировать критичные данные из persistent storage в StateEngine.

        Восстанавливает в StateEngine данные из app-defined namespaces
        для быстрого доступа при старте.
        """
        critical_prefixes = self.critical_state_prefixes
        if not critical_prefixes:
            return

        try:
            all_namespaces = await self.storage.list_namespaces()

            for namespace in all_namespaces:
                is_critical = any(
                    namespace.startswith(prefix) for prefix in critical_prefixes
                )

                if is_critical:
                    hydrated_count = 0
                    try:
                        async for key, value in self.storage.iter_namespace(namespace):
                            state_key = f"{namespace}.{key}"
                            await self.state_engine.set(state_key, value)
                            hydrated_count += 1
                    except Exception as e:
                        await warning(
                            self,
                            f"Ошибка при гидратации namespace '{namespace}': {e}",
                            component="runtime",
                        )

                    if hydrated_count > 0:
                        await info(
                            self,
                            f"Гидратирован namespace '{namespace}' ({hydrated_count} ключей)",
                            component="runtime",
                        )
        except Exception as e:
            await warning(
                self,
                f"Ошибка гидратации critical state: {e}. Система продолжит работу, но может быть медленнее.",
                component="runtime",
            )

    async def start(self) -> None:
        """
        Запустить Core Runtime.

        Runtime НЕ стартует, если хоть один REQUIRED RuntimeModule:
        - не зарегистрировался
        - не смог выполниться register()
        - упал в start()

        Гарантии:
        - Все REQUIRED модули должны быть зарегистрированы и запущены
        - При ошибке старта REQUIRED модуля runtime останавливается
        - stop_all() вызывается даже при частичном старте

        Raises:
            RuntimeError: если REQUIRED модуль не зарегистрирован или не запустился
        """
        if self._running:
            return

        try:
            middleware_names = await self.event_bus.list_middleware()
            middleware_factory = self.event_validation_middleware_factory
            if callable(middleware_factory):
                middleware = middleware_factory()
                middleware_name = type(middleware).__name__
                if middleware_name not in middleware_names:
                    await self.event_bus.add_middleware(middleware)

            self.module_manager.check_required_modules_registered()

            modules = self.module_manager.list_modules()
            if modules:
                await info(
                    self, f"Модули зарегистрированы: {modules}", component="runtime"
                )

            await self._hydrate_critical_state()

            await self.module_manager.start_all()
            if modules:
                await info(self, f"Модули запущены: {modules}", component="runtime")

            plugins = await self.plugin_manager.list_plugins()
            await info(
                self,
                "RUNTIME: about to call plugin_manager.start_all()",
                component="runtime",
            )
            await self.plugin_manager.start_all()
            await info(
                self,
                "RUNTIME: plugin_manager.start_all() returned",
                component="runtime",
            )

            if plugins:
                await info(self, f"Плагины запущены: {plugins}", component="runtime")

            integrity_errors = self.dependency_resolver.validate_runtime_integrity()
            if integrity_errors:
                raise RuntimeIntegrityError(integrity_errors)

            await self.state_engine.set("runtime.status", "running")
            self._running = True
            self._start_time = time.time()

            if self.worker is None:
                from core.operations.worker import OperationWorker

                self.worker = OperationWorker(self)
            if self._worker_task is None or self._worker_task.done():
                self._worker_task = asyncio.create_task(self.worker.start())
                self.worker._task = self._worker_task

        except Exception as e:
            try:
                await self.module_manager.stop_all()
            except Exception as stop_error:
                await warning(
                    self,
                    f"Ошибка при остановке модулей после ошибки старта: {stop_error}",
                    component="runtime",
                )
            raise

    async def stop(self) -> None:
        """
        Остановить Core Runtime.

        - сигналит HTTP серверу (should_exit)
        - останавливает все плагины
        - очищает состояние
        - закрывает storage

        Использует timeout из конфига (если доступен) для защиты от зависания.
        """
        if not self._running:
            return

        timeout = 10
        if self._config is not None:
            timeout = getattr(self._config, "shutdown_timeout", 10)

        async def _stop_internal() -> None:
            if self.worker is not None:
                await self.worker.stop()

            await self.plugin_manager.stop_all()
            await self.module_manager.stop_all()
            await self.storage.close()

            await self.state_engine.set("runtime.status", "stopped")
            self._running = False
            self._worker_task = None

        try:
            await asyncio.wait_for(_stop_internal(), timeout=timeout)
        except asyncio.TimeoutError:
            try:
                await warning(
                    self,
                    f"Timeout ({timeout}s) при остановке runtime, принудительное завершение",
                    component="runtime",
                )
            except Exception:
                pass
            self._running = False
            raise

    async def shutdown(self) -> None:
        """
        Полное завершение работы Runtime.

        - останавливает runtime
        - очищает все компоненты
        """
        await self.stop()

        self.module_manager.clear()

        await self.event_bus.clear()
        await self.service_registry.clear()
        await self.state_engine.clear()

    async def health_check(self) -> Dict[str, Any]:
        """
        Проверка здоровья всех компонентов runtime.

        Returns:
            Словарь с результатами проверки здоровья компонентов
        """
        collector = self.runtime_health_check
        if callable(collector):
            return await collector(self)

        checks: Dict[str, Any] = {}
        try:
            await self.storage.get("health_check", "test")
            checks["storage"] = "healthy"
            status = "healthy"
        except Exception as exc:
            checks["storage"] = "unhealthy"
            checks["storage_error"] = str(exc)
            status = "unhealthy"
        return {
            "status": status,
            "uptime": time.time() - self._start_time if self._start_time else 0,
            "checks": checks,
        }

    async def get_metrics(self) -> Dict[str, Any]:
        """
        Получить метрики runtime.

        Returns:
            Словарь с метриками плагинов, модулей, сервисов и storage
        """
        collector = self.runtime_metrics_collector
        if callable(collector):
            return await collector(self)

        metrics: Dict[str, Any] = {
            "uptime": time.time() - self._start_time if self._start_time else 0,
            "plugins": {},
            "modules": {},
            "services": {},
            "storage": {},
            "http_endpoints": {},
        }
        try:
            await self.storage.get("metrics", "test")
            metrics["storage"] = {"available": True}
        except Exception as exc:
            metrics["storage"] = {"available": False, "error": str(exc)}
        return metrics
