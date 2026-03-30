"""
RuntimeMonitor — компонент мониторинга, health checks и metrics.

Отвечает за:
- Health checks компонентов
- Сбор метрик runtime
- Мониторинг состояния

Этот класс инкапсулирует логику мониторинга,
освобождая CoreRuntime от этих обязанностей.
"""

import time
from typing import Any, Awaitable, Callable, Dict, Optional


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
        except Exception as exc:
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
        except Exception as exc:
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
