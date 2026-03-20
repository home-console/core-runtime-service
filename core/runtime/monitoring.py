"""
Core Runtime Monitoring & Diagnostics (D1).

Мониторинг здоровья и метрик runtime:
- health_check() - проверка здоровья всех компонентов
- get_metrics() - сбор метрик по плагинам, модулям, сервисам
"""

from typing import Dict, Any, TYPE_CHECKING
import time
from enum import Enum

from core.plugins import PluginState

if TYPE_CHECKING:
    from core.runtime import CoreRuntime


class HealthStatus(Enum):
    """Статусы здоровья компонентов."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


async def health_check(runtime: "CoreRuntime") -> Dict[str, Any]:
    """
    Проверка здоровья всех компонентов runtime.
    
    Returns:
        Словарь с результатами проверки здоровья компонентов
    """
    checks: Dict[str, str] = {}
    
    # Проверка Storage
    try:
        await runtime.storage.get("health_check", "test")
        checks["storage"] = HealthStatus.HEALTHY.value
    except Exception as e:
        checks["storage"] = HealthStatus.UNHEALTHY.value
        checks["storage_error"] = str(e)
    
    # Проверка модулей
    try:
        modules = runtime.module_manager.list_modules()
        required_modules = runtime.module_manager.get_required_modules()
        missing_required = [m for m in required_modules if m not in modules]
        if missing_required:
            checks["modules"] = HealthStatus.UNHEALTHY.value
            checks["modules_error"] = f"Missing required modules: {missing_required}"
        else:
            checks["modules"] = HealthStatus.HEALTHY.value
    except Exception as e:
        checks["modules"] = HealthStatus.UNHEALTHY.value
        checks["modules_error"] = str(e)
    
    # Проверка плагинов
    try:
        plugins = await runtime.plugin_manager.list_plugins()
        error_plugins = []
        for p in plugins:
            if await runtime.plugin_manager.get_plugin_state(p) == PluginState.ERROR:
                error_plugins.append(p)
        if error_plugins:
            checks["plugins"] = HealthStatus.DEGRADED.value
            checks["plugins_error"] = f"Plugins in error state: {error_plugins}"
        else:
            checks["plugins"] = HealthStatus.HEALTHY.value
    except Exception as e:
        checks["plugins"] = HealthStatus.UNHEALTHY.value
        checks["plugins_error"] = str(e)
    
    # Определяем общий статус
    overall = HealthStatus.HEALTHY
    if any(c == HealthStatus.UNHEALTHY.value for c in checks.values()):
        overall = HealthStatus.UNHEALTHY
    elif any(c == HealthStatus.DEGRADED.value for c in checks.values()):
        overall = HealthStatus.DEGRADED
    
    return {
        "status": overall.value,
        "uptime": time.time() - runtime._start_time if runtime._start_time else 0,
        "checks": checks
    }


async def get_metrics(runtime: "CoreRuntime") -> Dict[str, Any]:
    """
    Получить метрики runtime.
    
    Returns:
        Словарь с метриками плагинов, модулей, сервисов и storage
    """
    metrics: Dict[str, Any] = {
        "uptime": time.time() - runtime._start_time if runtime._start_time else 0
    }
    
    # Метрики плагинов
    try:
        plugins = await runtime.plugin_manager.list_plugins()
        plugin_states = {}
        for plugin_name in plugins:
            state = await runtime.plugin_manager.get_plugin_state(plugin_name)
            if state:
                plugin_states[plugin_name] = state.value
        
        started_count = sum(
            1 for state in plugin_states.values()
            if state == PluginState.STARTED.value
        )
        
        metrics["plugins"] = {
            "total": len(plugins),
            "started": started_count,
            "states": plugin_states
        }
    except Exception:
        metrics["plugins"] = {"error": "failed to collect"}
    
    # Метрики модулей
    try:
        modules = runtime.module_manager.list_modules()
        metrics["modules"] = {
            "total": len(modules),
            "list": modules
        }
    except Exception:
        metrics["modules"] = {"error": "failed to collect"}
    
    # Метрики сервисов
    try:
        services = await runtime.service_registry.list_services()
        metrics["services"] = {
            "total": len(services)
        }
    except Exception:
        metrics["services"] = {"error": "failed to collect"}
    
    # Метрики storage
    try:
        # Проверяем доступность storage
        await runtime.storage.get("metrics", "test")
        metrics["storage"] = {
            "available": True,
            "type": runtime.storage.get_backend_name(),
        }
    except Exception as e:
        metrics["storage"] = {
            "available": False,
            "error": str(e)
        }
    
    # Метрики HTTP endpoints
    try:
        endpoints = runtime.http.list()
        metrics["http_endpoints"] = {
            "total": len(endpoints),
            "by_method": {}
        }
        for endpoint in endpoints:
            method = endpoint.method
            if method not in metrics["http_endpoints"]["by_method"]:
                metrics["http_endpoints"]["by_method"][method] = 0
            metrics["http_endpoints"]["by_method"][method] += 1
    except Exception:
        metrics["http_endpoints"] = {"error": "failed to collect"}
    
    return metrics
