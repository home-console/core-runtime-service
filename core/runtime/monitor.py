"""
RuntimeMonitor — компонент мониторинга, health checks и metrics.

Отвечает за:
- Health checks компонентов
- Сбор метрик runtime
- Мониторинг состояния

Этот класс инкапсулирует логику мониторинга,
освобождая CoreRuntime от этих обязанностей.
"""

import logging
import time
from typing import Any, Awaitable, Callable, Dict, Optional

from core.adapters.storage_errors import STORAGE_BOUNDARY_ERRORS
from core.exception_groups import BEST_EFFORT_BACKGROUND_ERRORS

logger = logging.getLogger(__name__)


class RuntimeMonitor:
    """
    Компонент мониторинга runtime.

    Отвечает за:
    - Health checks компонентов
    - Сбор метрик runtime
    - Мониторинг состояния

    Использование:
        monitor = RuntimeMonitor(runtime)
        health = await monitor.health_check()
        metrics = await monitor.get_metrics()
    """

    def __init__(
        self,
        runtime: Any,
        health_check_delegate: Optional[Callable[[Any], Awaitable[Dict[str, Any]]]] = None,
        metrics_collector_delegate: Optional[Callable[[Any], Awaitable[Dict[str, Any]]]] = None,
    ):
        """
        Инициализация компонента мониторинга.

        Args:
            runtime: экземпляр CoreRuntime (или совместимый объект)
            health_check_delegate: опциональная функция для health check (из app)
            metrics_collector_delegate: опциональная функция для сбора метрик (из app)
        """
        self.runtime = runtime
        self.health_check_delegate = health_check_delegate
        self.metrics_collector_delegate = metrics_collector_delegate

    async def health_check(self) -> Dict[str, Any]:
        """
        Проверка здоровья всех компонентов runtime.

        Returns:
            Словарь с результатами проверки здоровья компонентов
        """
        # Используем delegate из app если доступен
        if callable(self.health_check_delegate):
            return await self.health_check_delegate(self.runtime)

        # Fallback на базовую проверку
        checks: Dict[str, Any] = {}
        status = "healthy"

        try:
            # Проверка storage
            await self.runtime.storage.get("health_check", "test")
            checks["storage"] = "healthy"
        except STORAGE_BOUNDARY_ERRORS as exc:
            logger.debug(
                "monitor.health_check: storage boundary: %s",
                exc,
                exc_info=True,
            )
            checks["storage"] = "unhealthy"
            checks["storage_error"] = str(exc)
            checks["storage_error_kind"] = "storage_boundary"
            status = "unhealthy"
        except BEST_EFFORT_BACKGROUND_ERRORS as exc:
            logger.debug(
                "monitor.health_check: unexpected storage error: %s",
                exc,
                exc_info=True,
            )
            checks["storage"] = "unhealthy"
            checks["storage_error"] = str(exc)
            status = "unhealthy"

        return {
            "status": status,
            "uptime": self.get_uptime(),
            "checks": checks,
        }

    async def get_metrics(self) -> Dict[str, Any]:
        """
        Получить метрики runtime.

        Returns:
            Словарь с метриками
        """
        # Используем delegate из app если доступен
        if callable(self.metrics_collector_delegate):
            return await self.metrics_collector_delegate(self.runtime)

        # Fallback на базовые метрики
        metrics: Dict[str, Any] = {
            "uptime": self.get_uptime(),
            "plugins": {},
            "modules": {},
            "services": {},
            "storage": {},
            "http_endpoints": {},
        }

        try:
            await self.runtime.storage.get("metrics", "test")
            metrics["storage"] = {"available": True}
        except STORAGE_BOUNDARY_ERRORS as exc:
            logger.debug(
                "monitor.get_metrics: storage boundary: %s",
                exc,
                exc_info=True,
            )
            metrics["storage"] = {
                "available": False,
                "error": str(exc),
                "error_kind": "storage_boundary",
            }
        except BEST_EFFORT_BACKGROUND_ERRORS as exc:
            logger.debug(
                "monitor.get_metrics: unexpected storage error: %s",
                exc,
                exc_info=True,
            )
            metrics["storage"] = {"available": False, "error": str(exc)}

        return metrics

    def get_uptime(self) -> float:
        """
        Получить время работы runtime в секундах.

        Returns:
            Uptime в секундах
        """
        start_time = getattr(self.runtime, "_start_time", None)
        if start_time is None:
            return 0.0
        return time.time() - start_time

    def is_running(self) -> bool:
        """
        Проверить, запущен ли runtime.

        Returns:
            True если runtime запущен
        """
        return getattr(self.runtime, "_running", False)
