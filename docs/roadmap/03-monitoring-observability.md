# 📊 Monitoring & Observability — Мониторинг и наблюдаемость

**Приоритет:** 🟡 ВЫСОКИЙ  
**Срок:** 1 неделя  
**Ответственный:** DevOps + Dev Team

---

## 🎯 Цель

Внедрить полноценный мониторинг и observability для production-ready системы.

---

## 📊 Текущее состояние

### Что есть:
- ✅ System Logger Plugin (базовое логирование)
- ✅ Структурированные логи (JSON)

### Что отсутствует:
- ❌ Метрики производительности (Prometheus)
- ❌ Distributed tracing
- ❌ Health checks для плагинов
- ❌ Alerting система
- ❌ Performance profiling
- ❌ Error tracking (Sentry-like)
- ❌ Dashboard для визуализации

---

## 📋 План действий

### День 1-2: MonitoringModule

#### Структура модуля:
```python
modules/monitoring/
├── __init__.py
├── module.py              # MonitoringModule
├── metrics.py             # Prometheus metrics
├── health_checks.py       # Health checking system
├── tracing.py             # Distributed tracing
└── alerts.py              # Alerting system
```

#### module.py

```python
"""
Monitoring Module — мониторинг и observability.

Предоставляет:
- Prometheus metrics
- Health checks
- Distributed tracing
- Alerting
"""
from typing import TYPE_CHECKING
from core.runtime_module import RuntimeModule

if TYPE_CHECKING:
    from core.runtime.runtime import CoreRuntime


class MonitoringModule(RuntimeModule):
    """
    Модуль мониторинга и observability.
    
    Сервисы:
    - monitoring.record_metric - запись метрики
    - monitoring.health_check - проверка здоровья компонента
    - monitoring.start_span - начало trace span
    """

    @property
    def name(self) -> str:
        return "monitoring"

    def __init__(self, runtime: "CoreRuntime"):
        super().__init__(runtime)
        self.metrics = None
        self.health_checker = None
        self.tracer = None

    async def register(self) -> None:
        """Регистрация сервисов."""
        from .metrics import MetricsCollector
        from .health_checks import HealthChecker
        from .tracing import TracingSystem

        # Инициализация компонентов
        self.metrics = MetricsCollector()
        self.health_checker = HealthChecker(self.runtime)
        self.tracer = TracingSystem()

        # Регистрация сервисов
        await self.runtime.service_registry.register(
            "monitoring.record_metric",
            self._record_metric
        )
        await self.runtime.service_registry.register(
            "monitoring.health_check",
            self._health_check
        )
        await self.runtime.service_registry.register(
            "monitoring.start_span",
            self._start_span
        )

    async def start(self) -> None:
        """Запуск мониторинга."""
        # Подписка на системные события для метрик
        await self.runtime.event_bus.subscribe(
            "internal.*",
            self._track_event
        )

        # Запуск health checker
        await self.health_checker.start()

    async def _record_metric(
            self,
            name: str,
            value: float,
            labels: dict = None
    ):
        """Запись метрики."""
        self.metrics.record(name, value, labels or {})

    async def _health_check(self, component: str) -> dict:
        """Проверка здоровья компонента."""
        return await self.health_checker.check(component)

    async def _start_span(self, operation: str) -> str:
        """Начать trace span."""
        return self.tracer.start_span(operation)

    async def _track_event(self, event_type: str, data: dict):
        """Трекинг событий для метрик."""
        # Считаем количество событий по типам
        self.metrics.increment(
            "events_total",
            labels={"event_type": event_type}
        )
```

#### metrics.py
```python
"""
Prometheus metrics collector.
"""
from prometheus_client import Counter, Histogram, Gauge, generate_latest
from typing import Dict
import time


class MetricsCollector:
    """Сборщик метрик в формате Prometheus."""
    
    def __init__(self):
        # System metrics
        self.events_total = Counter(
            'homeconsole_events_total',
            'Total number of events',
            ['event_type']
        )
        
        self.service_calls_total = Counter(
            'homeconsole_service_calls_total',
            'Total number of service calls',
            ['service_name', 'status']
        )
        
        self.service_call_duration = Histogram(
            'homeconsole_service_call_duration_seconds',
            'Service call duration',
            ['service_name']
        )
        
        # Storage metrics
        self.storage_operations = Counter(
            'homeconsole_storage_operations_total',
            'Storage operations',
            ['operation', 'namespace']
        )
        
        self.storage_operation_duration = Histogram(
            'homeconsole_storage_operation_duration_seconds',
            'Storage operation duration',
            ['operation']
        )
        
        # Plugin metrics
        self.plugins_loaded = Gauge(
            'homeconsole_plugins_loaded',
            'Number of loaded plugins'
        )
        
        self.plugin_state = Gauge(
            'homeconsole_plugin_state',
            'Plugin state (1=started, 0=stopped)',
            ['plugin_name']
        )
    
    def record(self, name: str, value: float, labels: Dict[str, str]):
        """Запись произвольной метрики."""
        # Динамическое создание метрик если нужно
        pass
    
    def increment(self, name: str, labels: Dict[str, str]):
        """Инкремент счётчика."""
        if name == "events_total":
            self.events_total.labels(**labels).inc()
        elif name == "service_calls_total":
            self.service_calls_total.labels(**labels).inc()
    
    def export(self) -> bytes:
        """Экспорт метрик в Prometheus формате."""
        return generate_latest()
```

#### health_checks.py
```python
"""
Health checking system.
"""
import asyncio
from typing import Dict, List
from enum import Enum


class HealthStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class HealthChecker:
    """Система проверки здоровья компонентов."""
    
    def __init__(self, runtime):
        self.runtime = runtime
        self.checks = {}
        self._task = None
    
    async def start(self):
        """Запуск периодических проверок."""
        self._task = asyncio.create_task(self._check_loop())
    
    async def stop(self):
        """Остановка проверок."""
        if self._task:
            self._task.cancel()
    
    async def _check_loop(self):
        """Периодическая проверка всех компонентов."""
        while True:
            await asyncio.sleep(30)  # Каждые 30 секунд
            await self._check_all()
    
    async def _check_all(self):
        """Проверить все компоненты."""
        # Storage
        await self.check("storage")
        
        # Modules
        for module_name in self.runtime.module_manager.list_modules():
            await self.check(f"module:{module_name}")
        
        # Plugins
        for plugin_name in self.runtime.plugin_manager.list_plugins():
            await self.check(f"plugin:{plugin_name}")
    
    async def check(self, component: str) -> dict:
        """
        Проверить здоровье компонента.
        
        Returns:
            {
                "status": "healthy" | "degraded" | "unhealthy",
                "message": "...",
                "checks": {
                    "connectivity": true,
                    "response_time": 0.05
                }
            }
        """
        if component == "storage":
            return await self._check_storage()
        elif component.startswith("module:"):
            module_name = component.split(":")[1]
            return await self._check_module(module_name)
        elif component.startswith("plugin:"):
            plugin_name = component.split(":")[1]
            return await self._check_plugin(plugin_name)
        
        return {
            "status": HealthStatus.UNHEALTHY.value,
            "message": "Unknown component"
        }
    
    async def _check_storage(self) -> dict:
        """Проверка storage."""
        try:
            import time
            start = time.time()
            
            # Пробуем записать и прочитать
            await self.runtime.storage.set(
                "health_check",
                "test",
                {"timestamp": time.time()}
            )
            result = await self.runtime.storage.get("health_check", "test")
            
            duration = time.time() - start
            
            if result and duration < 1.0:
                return {
                    "status": HealthStatus.HEALTHY.value,
                    "message": "Storage operational",
                    "checks": {
                        "connectivity": True,
                        "response_time": duration
                    }
                }
            else:
                return {
                    "status": HealthStatus.DEGRADED.value,
                    "message": "Storage slow",
                    "checks": {
                        "connectivity": True,
                        "response_time": duration
                    }
                }
        except Exception as e:
            return {
                "status": HealthStatus.UNHEALTHY.value,
                "message": f"Storage error: {e}",
                "checks": {"connectivity": False}
            }
    
    async def _check_module(self, module_name: str) -> dict:
        """Проверка модуля."""
        module = self.runtime.module_manager.get_module(module_name)
        if module:
            return {
                "status": HealthStatus.HEALTHY.value,
                "message": "Module operational"
            }
        else:
            return {
                "status": HealthStatus.UNHEALTHY.value,
                "message": "Module not found"
            }
    
    async def _check_plugin(self, plugin_name: str) -> dict:
        """Проверка плагина."""
        state = self.runtime.plugin_manager.get_state(plugin_name)
        if state == "started":
            return {
                "status": HealthStatus.HEALTHY.value,
                "message": "Plugin running"
            }
        elif state == "stopped":
            return {
                "status": HealthStatus.DEGRADED.value,
                "message": "Plugin stopped"
            }
        else:
            return {
                "status": HealthStatus.UNHEALTHY.value,
                "message": f"Plugin in error state: {state}"
            }
```

---

### День 3-4: HTTP endpoints для метрик

#### В ApiModule добавить:
```python
# GET /api/v1/monitoring/metrics
# Prometheus metrics endpoint

@app.get("/api/v1/monitoring/metrics")
async def get_metrics():
    """Prometheus metrics endpoint."""
    monitoring_module = runtime.module_manager.get_module("monitoring")
    metrics = monitoring_module.metrics.export()
    return Response(content=metrics, media_type="text/plain")


# GET /api/v1/monitoring/health
# Health check endpoint

@app.get("/api/v1/monitoring/health")
async def health_check():
    """Overall system health."""
    monitoring_module = runtime.module_manager.get_module("monitoring")
    
    results = {
        "storage": await monitoring_module.health_checker.check("storage"),
        "modules": {},
        "plugins": {}
    }
    
    # Check all modules
    for module_name in runtime.module_manager.list_modules():
        results["modules"][module_name] = \
            await monitoring_module.health_checker.check(f"module:{module_name}")
    
    # Check all plugins
    for plugin_name in runtime.plugin_manager.list_plugins():
        results["plugins"][plugin_name] = \
            await monitoring_module.health_checker.check(f"plugin:{plugin_name}")
    
    # Determine overall status
    all_statuses = [
        results["storage"]["status"],
        *[m["status"] for m in results["modules"].values()],
        *[p["status"] for p in results["plugins"].values()]
    ]
    
    if all(s == "healthy" for s in all_statuses):
        overall = "healthy"
        status_code = 200
    elif any(s == "unhealthy" for s in all_statuses):
        overall = "unhealthy"
        status_code = 503
    else:
        overall = "degraded"
        status_code = 200
    
    return JSONResponse(
        content={"status": overall, "checks": results},
        status_code=status_code
    )
```

---

### День 5: Grafana dashboard

#### Создать docker-compose для мониторинга:
```yaml
# docker-compose.monitoring.yml
version: '3.8'

services:
  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9090:9090"
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus_data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
  
  grafana:
    image: grafana/grafana:latest
    ports:
      - "3001:3000"
    volumes:
      - grafana_data:/var/lib/grafana
      - ./monitoring/grafana-dashboards:/etc/grafana/provisioning/dashboards
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin

volumes:
  prometheus_data:
  grafana_data:
```

#### prometheus.yml
```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'homeconsole'
    static_configs:
      - targets: ['host.docker.internal:8000']
    metrics_path: '/api/v1/monitoring/metrics'
```

---

## 🎯 Критерии успеха

- ✅ MonitoringModule реализован
- ✅ Prometheus metrics экспортируются
- ✅ Health checks работают для всех компонентов
- ✅ Grafana dashboard настроен
- ✅ Alerting правила определены
- ✅ Документация написана

---

## 📝 Checklist

### Разработка
- [ ] MonitoringModule
- [ ] MetricsCollector
- [ ] HealthChecker
- [ ] HTTP endpoints
- [ ] Тесты для monitoring

### Инфраструктура
- [ ] docker-compose.monitoring.yml
- [ ] prometheus.yml
- [ ] Grafana dashboards
- [ ] Alert rules

### Документация
- [ ] docs/MONITORING.md
- [ ] README обновлён
- [ ] Примеры использования

---

## 📊 Прогресс

**Статус:** 🔴 Не начато  
**Дата начала:** TBD  
**Дата завершения:** TBD
