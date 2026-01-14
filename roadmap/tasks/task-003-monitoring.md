# 📊 Task 003: Monitoring Module

**Приоритет:** 🟡 ВЫСОКИЙ  
**Срок:** 8 часов  
**Ответственный:** Dev Team  
**Статус:** 🔴 Не начато

---

## 🎯 Цель

Создать MonitoringModule с Prometheus metrics и health checks.

---

## 📋 Подзадачи

### 1. Структура модуля (1 час)

```bash
cd core-runtime-service
mkdir -p modules/monitoring
touch modules/monitoring/__init__.py
touch modules/monitoring/module.py
touch modules/monitoring/metrics.py
touch modules/monitoring/health_checks.py
```

### 2. Базовый MonitoringModule (2 часа)

Создать `modules/monitoring/module.py`:
```python
"""
Monitoring Module — мониторинг и observability.
"""
from typing import TYPE_CHECKING
from core.runtime_module import RuntimeModule

if TYPE_CHECKING:
    from core.runtime import CoreRuntime


class MonitoringModule(RuntimeModule):
    """Модуль мониторинга."""
    
    @property
    def name(self) -> str:
        return "monitoring"
    
    def __init__(self, runtime: "CoreRuntime"):
        super().__init__(runtime)
        self.metrics = None
        self.health_checker = None
    
    async def register(self) -> None:
        """Регистрация сервисов мониторинга."""
        from .metrics import MetricsCollector
        from .health_checks import HealthChecker
        
        self.metrics = MetricsCollector()
        self.health_checker = HealthChecker(self.runtime)
        
        # Регистрация сервисов
        await self.runtime.service_registry.register(
            "monitoring.record_metric",
            self._record_metric
        )
        await self.runtime.service_registry.register(
            "monitoring.health_check",
            self._health_check
        )
    
    async def start(self) -> None:
        """Запуск мониторинга."""
        # Подписка на системные события
        await self.runtime.event_bus.subscribe(
            "internal.*",
            self._track_event
        )
        
        # Запуск health checker
        await self.health_checker.start()
    
    async def stop(self) -> None:
        """Остановка мониторинга."""
        if self.health_checker:
            await self.health_checker.stop()
    
    async def _record_metric(self, name: str, value: float, labels: dict = None):
        """Запись метрики."""
        self.metrics.record(name, value, labels or {})
    
    async def _health_check(self, component: str) -> dict:
        """Проверка здоровья компонента."""
        return await self.health_checker.check(component)
    
    async def _track_event(self, event_type: str, data: dict):
        """Трекинг событий."""
        self.metrics.increment("events_total", {"event_type": event_type})
```

### 3. Metrics Collector (2 часа)

Создать `modules/monitoring/metrics.py`:
```python
"""
Prometheus metrics collector.
"""
from prometheus_client import Counter, Histogram, Gauge, generate_latest
from typing import Dict


class MetricsCollector:
    """Сборщик метрик Prometheus."""
    
    def __init__(self):
        # События
        self.events_total = Counter(
            'homeconsole_events_total',
            'Total number of events',
            ['event_type']
        )
        
        # Сервисы
        self.service_calls_total = Counter(
            'homeconsole_service_calls_total',
            'Total service calls',
            ['service_name', 'status']
        )
        
        self.service_call_duration = Histogram(
            'homeconsole_service_call_duration_seconds',
            'Service call duration',
            ['service_name']
        )
        
        # Storage
        self.storage_operations = Counter(
            'homeconsole_storage_operations_total',
            'Storage operations',
            ['operation', 'namespace']
        )
        
        # Плагины
        self.plugins_loaded = Gauge(
            'homeconsole_plugins_loaded',
            'Number of loaded plugins'
        )
    
    def increment(self, name: str, labels: Dict[str, str]):
        """Инкремент счётчика."""
        if name == "events_total":
            self.events_total.labels(**labels).inc()
        elif name == "service_calls_total":
            self.service_calls_total.labels(**labels).inc()
        elif name == "storage_operations":
            self.storage_operations.labels(**labels).inc()
    
    def record(self, name: str, value: float, labels: Dict[str, str]):
        """Запись метрики."""
        if name == "service_call_duration":
            self.service_call_duration.labels(**labels).observe(value)
    
    def set_gauge(self, name: str, value: float):
        """Установить gauge."""
        if name == "plugins_loaded":
            self.plugins_loaded.set(value)
    
    def export(self) -> bytes:
        """Экспорт в Prometheus формате."""
        return generate_latest()
```

### 4. Health Checker (2 часа)

Создать `modules/monitoring/health_checks.py`:
```python
"""
Health checking system.
"""
import asyncio
from typing import Dict
from enum import Enum


class HealthStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class HealthChecker:
    """Проверка здоровья компонентов."""
    
    def __init__(self, runtime):
        self.runtime = runtime
        self._task = None
    
    async def start(self):
        """Запуск периодических проверок."""
        self._task = asyncio.create_task(self._check_loop())
    
    async def stop(self):
        """Остановка."""
        if self._task:
            self._task.cancel()
    
    async def _check_loop(self):
        """Периодическая проверка (каждые 30 сек)."""
        while True:
            await asyncio.sleep(30)
            await self._check_all()
    
    async def _check_all(self):
        """Проверить все компоненты."""
        await self.check("storage")
        
        for module_name in self.runtime.module_manager.list_modules():
            await self.check(f"module:{module_name}")
    
    async def check(self, component: str) -> dict:
        """Проверить компонент."""
        if component == "storage":
            return await self._check_storage()
        elif component.startswith("module:"):
            module_name = component.split(":")[1]
            return await self._check_module(module_name)
        
        return {
            "status": HealthStatus.UNHEALTHY.value,
            "message": "Unknown component"
        }
    
    async def _check_storage(self) -> dict:
        """Проверка storage."""
        try:
            import time
            start = time.time()
            
            await self.runtime.storage.set(
                "health_check", "test", {"timestamp": time.time()}
            )
            result = await self.runtime.storage.get("health_check", "test")
            
            duration = time.time() - start
            
            if result and duration < 1.0:
                return {
                    "status": HealthStatus.HEALTHY.value,
                    "message": "Storage operational",
                    "checks": {"response_time": duration}
                }
            else:
                return {
                    "status": HealthStatus.DEGRADED.value,
                    "message": "Storage slow"
                }
        except Exception as e:
            return {
                "status": HealthStatus.UNHEALTHY.value,
                "message": f"Storage error: {e}"
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
```

### 5. HTTP Endpoints (1 час)

Добавить в `modules/api/module.py`:
```python
@self.app.get("/api/v1/monitoring/metrics")
async def get_metrics():
    """Prometheus metrics."""
    monitoring = runtime.module_manager.get_module("monitoring")
    if not monitoring:
        raise HTTPException(404, "Monitoring module not loaded")
    
    metrics = monitoring.metrics.export()
    return Response(content=metrics, media_type="text/plain")


@self.app.get("/api/v1/monitoring/health")
async def health_check():
    """Health check."""
    monitoring = runtime.module_manager.get_module("monitoring")
    if not monitoring:
        return {"status": "unhealthy", "message": "Monitoring not available"}
    
    storage_health = await monitoring.health_checker.check("storage")
    
    return {
        "status": storage_health["status"],
        "checks": {
            "storage": storage_health
        }
    }
```

---

## ✅ Acceptance Criteria

- [ ] MonitoringModule создан
- [ ] MetricsCollector работает
- [ ] HealthChecker работает
- [ ] HTTP endpoints `/metrics` и `/health` доступны
- [ ] Тесты написаны
- [ ] Документация добавлена

---

## 🚀 Проверка

```bash
# Запустить runtime
cd core-runtime-service
python main.py

# Проверить metrics
curl http://localhost:8000/api/v1/monitoring/metrics

# Проверить health
curl http://localhost:8000/api/v1/monitoring/health

# Должен вернуть:
# {"status": "healthy", "checks": {...}}
```

---

## 📝 Установить зависимости

```bash
# Добавить в requirements.txt
echo "prometheus-client>=0.19.0" >> requirements.txt

pip install prometheus-client
```

---

## 🔗 Ссылки

- **Roadmap:** [../ROADMAP.md](../../ROADMAP.md)
- **Monitoring Strategy:** [../03-monitoring-observability.md](../03-monitoring-observability.md)
- **Prometheus:** https://prometheus.io/
- **Prometheus Python Client:** https://github.com/prometheus/client_python

---

## 📊 Прогресс

**Статус:** 🔴 Не начато  
**Затрачено:** 0/8 часов  
**Дата начала:** TBD  
**Дата завершения:** TBD
