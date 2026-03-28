"""
Metrics Registry — production-grade observability.

Thread-safe metrics collection in-memory.
No external dependencies (Prometheus optional future extension).

Metrics collected:
- operations_total (counter by operation_type)
- operations_failed_total
- operation_latency_seconds (histogram)
- plugin_load_total
- plugin_crash_total
- provider_failures_total
- provider_success_total
"""

import threading
import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Counter:
    """Thread-safe counter metric."""
    name: str
    value: int = 0
    labels: Dict[str, int] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    
    def increment(self, amount: int = 1, label_value: str = None) -> None:
        """Increment counter, optionally by label."""
        with self._lock:
            self.value += amount
            if label_value:
                self.labels[label_value] = self.labels.get(label_value, 0) + amount
    
    def get(self) -> int:
        """Get current value."""
        with self._lock:
            return self.value
    
    def get_by_label(self) -> Dict[str, int]:
        """Get labeled values."""
        with self._lock:
            return dict(self.labels)


@dataclass
class Gauge:
    """Thread-safe gauge metric (current value)."""
    name: str
    value: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock)
    
    def set(self, value: float) -> None:
        """Set gauge value."""
        with self._lock:
            self.value = value
    
    def get(self) -> float:
        """Get current value."""
        with self._lock:
            return self.value


@dataclass
class Histogram:
    """Thread-safe histogram metric."""
    name: str
    buckets: List[float] = field(default_factory=lambda: [0.001, 0.01, 0.1, 0.5, 1.0, 5.0, 10.0])
    observations: List[float] = field(default_factory=list)
    bucket_counts: Dict[float, int] = field(default_factory=dict)
    sum_value: float = 0.0
    count: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)
    
    def __post_init__(self):
        """Initialize bucket counts."""
        for bucket in self.buckets:
            self.bucket_counts[bucket] = 0
    
    def observe(self, value: float) -> None:
        """Record an observation."""
        with self._lock:
            self.observations.append(value)
            self.sum_value += value
            self.count += 1
            
            # Update bucket counts
            for bucket in self.buckets:
                if value <= bucket:
                    self.bucket_counts[bucket] += 1
    
    def get_stats(self) -> Dict[str, float]:
        """Get histogram statistics."""
        with self._lock:
            if self.count == 0:
                return {"count": 0, "sum": 0, "mean": 0, "min": 0, "max": 0}
            
            sorted_obs = sorted(self.observations)
            return {
                "count": self.count,
                "sum": self.sum_value,
                "mean": self.sum_value / self.count,
                "min": min(self.observations),
                "max": max(self.observations),
                "p50": sorted_obs[len(sorted_obs) // 2],
                "p95": sorted_obs[int(len(sorted_obs) * 0.95)],
                "p99": sorted_obs[int(len(sorted_obs) * 0.99)],
                "buckets": dict(self.bucket_counts),
            }


class MetricsRegistry:
    """
    Thread-safe metrics registry.
    
    Collects all system metrics in-memory.
    Can be extended to export to Prometheus/Datadog in future.
    """
    
    def __init__(self):
        self._counters: Dict[str, Counter] = {}
        self._gauges: Dict[str, Gauge] = {}
        self._histograms: Dict[str, Histogram] = {}
        self._lock = threading.RLock()
        
        # Initialize built-in metrics
        self._init_builtin_metrics()
    
    def _init_builtin_metrics(self) -> None:
        """Initialize standard metrics."""
        # Operations
        self._declare_counter("operations_total")
        self._declare_counter("operations_failed_total")
        self._declare_histogram("operation_latency_seconds")
        
        # Plugins
        self._declare_counter("plugin_load_total")
        self._declare_counter("plugin_crash_total")
        self._declare_gauge("plugins_active")
        
        # Providers
        self._declare_counter("provider_failures_total")
        self._declare_counter("provider_success_total")
        self._declare_gauge("provider_health_degraded")
        
        # Marketplace transaction metrics
        self._declare_counter("marketplace_transactions_committed")
        self._declare_counter("marketplace_transactions_rolled_back")
        self._declare_counter("marketplace_transactions_failed")
        
        # Rate limiting
        self._declare_counter("rate_limit_exceeded_total")
    
    def _declare_counter(self, name: str) -> Counter:
        """Declare a new counter metric."""
        with self._lock:
            if name not in self._counters:
                self._counters[name] = Counter(name=name)
            return self._counters[name]
    
    def _declare_gauge(self, name: str) -> Gauge:
        """Declare a new gauge metric."""
        with self._lock:
            if name not in self._gauges:
                self._gauges[name] = Gauge(name=name)
            return self._gauges[name]
    
    def _declare_histogram(self, name: str, buckets: List[float] = None) -> Histogram:
        """Declare a new histogram metric."""
        with self._lock:
            if name not in self._histograms:
                self._histograms[name] = Histogram(name=name, buckets=buckets or [])
            return self._histograms[name]
    
    def counter(self, name: str, label_value: str = None) -> Counter:
        """Get or create counter and optionally increment."""
        if name not in self._counters:
            self._declare_counter(name)
        return self._counters[name]
    
    def gauge(self, name: str) -> Gauge:
        """Get or create gauge."""
        if name not in self._gauges:
            self._declare_gauge(name)
        return self._gauges[name]
    
    def histogram(self, name: str, buckets: List[float] = None) -> Histogram:
        """Get or create histogram."""
        if name not in self._histograms:
            self._declare_histogram(name, buckets)
        return self._histograms[name]
    
    def increment_counter(self, name: str, amount: int = 1, label_value: str = None) -> None:
        """Increment a counter by name."""
        counter = self.counter(name)
        counter.increment(amount, label_value)
    
    def set_gauge(self, name: str, value: float) -> None:
        """Set a gauge value by name."""
        gauge = self.gauge(name)
        gauge.set(value)
    
    def observe_histogram(self, name: str, value: float) -> None:
        """Record histogram observation by name."""
        histogram = self.histogram(name)
        histogram.observe(value)
    
    def get_all_metrics(self) -> Dict[str, Dict[str, any]]:
        """Export all metrics as dict."""
        # Don't hold registry lock while accessing nested locks to avoid deadlock
        counters_data = {}
        for name, counter in self._counters.items():
            counters_data[name] = {
                "value": counter.get(),
                "labels": counter.get_by_label()
            }
        
        gauges_data = {}
        for name, gauge in self._gauges.items():
            gauges_data[name] = gauge.get()
        
        histograms_data = {}
        for name, histogram in self._histograms.items():
            histograms_data[name] = histogram.get_stats()
        
        return {
            "counters": counters_data,
            "gauges": gauges_data,
            "histograms": histograms_data,
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z"
        }
    
    def get_metric(self, name: str) -> Optional[Dict[str, any]]:
        """Get single metric by name."""
        all_metrics = self.get_all_metrics()
        
        for metric_type in ["counters", "gauges", "histograms"]:
            if name in all_metrics.get(metric_type, {}):
                return all_metrics[metric_type][name]
        
        return None
    
    def reset(self) -> None:
        """Reset all metrics (for testing)."""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()
            self._init_builtin_metrics()


# Global singleton instance
_metrics_registry: Optional[MetricsRegistry] = None


def get_metrics_registry() -> MetricsRegistry:
    """Get global metrics registry (lazy initialization)."""
    global _metrics_registry
    if _metrics_registry is None:
        _metrics_registry = MetricsRegistry()
    return _metrics_registry
