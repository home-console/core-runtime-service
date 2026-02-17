"""
Step 13: Observability Tests — metrics, health snapshots, and monitoring.

Tests for:
- MetricsRegistry (counters, gauges, histograms)
- HealthSnapshotCollector
- Integration with OperationManager
"""

import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch

from core.observability.metrics import (
    MetricsRegistry,
    Counter,
    Gauge,
    Histogram,
    get_metrics_registry,
)
from core.observability.health_snapshot import (
    HealthSnapshot,
    ProviderStatusSummary,
    HealthSnapshotCollector,
)


class TestCounter:
    """Test Counter metric."""
    
    def test_counter_increment(self):
        """Test counter increments correctly."""
        counter = Counter(name="test_counter")
        assert counter.get() == 0
        
        counter.increment()
        assert counter.get() == 1
        
        counter.increment(5)
        assert counter.get() == 6
    
    def test_counter_with_labels(self):
        """Test counter with label tracking."""
        counter = Counter(name="test_counter")
        
        counter.increment(label_value="op_type_1")
        counter.increment(label_value="op_type_2")
        counter.increment(label_value="op_type_1")
        
        labels = counter.get_by_label()
        assert labels == {"op_type_1": 2, "op_type_2": 1}
    
    def test_counter_thread_safe(self):
        """Test counter is thread-safe."""
        import threading
        
        counter = Counter(name="test_counter")
        success_count = [0]  # Use list for thread-safe mutation
        lock = threading.Lock()
        
        def increment_some():
            for _ in range(10):
                counter.increment()
                with lock:
                    success_count[0] += 1
        
        threads = [threading.Thread(target=increment_some) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # Should have incremented 50 times total
        assert counter.get() == 50


class TestGauge:
    """Test Gauge metric."""
    
    def test_gauge_set_get(self):
        """Test gauge set and get."""
        gauge = Gauge(name="test_gauge")
        
        gauge.set(42.0)
        assert gauge.get() == 42.0
        
        gauge.set(100.0)
        assert gauge.get() == 100.0
    
    def test_gauge_thread_safe(self):
        """Test gauge is thread-safe."""
        import threading
        
        gauge = Gauge(name="test_gauge")
        results = []
        lock = threading.Lock()
        
        def set_value(value):
            gauge.set(float(value))
            with lock:
                results.append(value)
        
        threads = [threading.Thread(target=set_value, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # Final value should be one of the set values
        assert 0 <= gauge.get() < 5


class TestHistogram:
    """Test Histogram metric."""
    
    def test_histogram_observe(self):
        """Test histogram observes values."""
        histogram = Histogram(name="test_histogram", buckets=[0.1, 1.0, 10.0])
        
        histogram.observe(0.05)
        histogram.observe(0.5)
        histogram.observe(5.0)
        
        stats = histogram.get_stats()
        assert stats["count"] == 3
        assert stats["sum"] == 5.55
        assert stats["min"] == 0.05
        assert stats["max"] == 5.0
    
    def test_histogram_percentiles(self):
        """Test histogram computes percentiles."""
        histogram = Histogram(name="test_histogram")
        
        for i in range(1, 101):
            histogram.observe(float(i))
        
        stats = histogram.get_stats()
        assert stats["p50"] >= 50  # approximately
        assert stats["p95"] >= 95  # approximately
        assert stats["p99"] >= 99  # approximately
    
    def test_histogram_buckets(self):
        """Test histogram bucket counting."""
        histogram = Histogram(name="test_histogram", buckets=[1.0, 5.0, 10.0])
        
        histogram.observe(0.5)   # <= 1.0
        histogram.observe(2.0)   # <= 5.0
        histogram.observe(7.0)   # <= 10.0
        histogram.observe(15.0)  # > 10.0
        
        stats = histogram.get_stats()
        assert stats["buckets"][1.0] == 1
        assert stats["buckets"][5.0] == 2
        assert stats["buckets"][10.0] == 3


class TestMetricsRegistry:
    """Test MetricsRegistry."""
    
    def test_registry_initialization(self):
        """Test registry initializes with built-in metrics."""
        registry = MetricsRegistry()
        
        assert "operations_total" in registry._counters
        assert "operations_failed_total" in registry._counters
        assert "operation_latency_seconds" in registry._histograms
        assert "plugins_active" in registry._gauges
    
    def test_registry_counter_operations(self):
        """Test counter operations via registry."""
        registry = MetricsRegistry()
        
        registry.increment_counter("operations_total")
        registry.increment_counter("operations_total")
        
        assert registry.counter("operations_total").get() == 2
    
    def test_registry_gauge_operations(self):
        """Test gauge operations via registry."""
        registry = MetricsRegistry()
        
        registry.set_gauge("plugins_active", 5.0)
        assert registry.gauge("plugins_active").get() == 5.0
    
    def test_registry_histogram_operations(self):
        """Test histogram operations via registry."""
        registry = MetricsRegistry()
        
        registry.observe_histogram("operation_latency_seconds", 0.5)
        registry.observe_histogram("operation_latency_seconds", 1.0)
        
        stats = registry.histogram("operation_latency_seconds").get_stats()
        assert stats["count"] == 2
    
    def test_registry_get_all_metrics(self):
        """Test getting all metrics as dict."""
        registry = MetricsRegistry()
        
        registry.increment_counter("operations_total")
        registry.set_gauge("plugins_active", 3.0)
        registry.observe_histogram("operation_latency_seconds", 0.1)
        
        all_metrics = registry.get_all_metrics()
        
        assert "counters" in all_metrics
        assert "gauges" in all_metrics
        assert "histograms" in all_metrics
        assert "timestamp" in all_metrics
    
    def test_registry_get_single_metric(self):
        """Test getting single metric."""
        registry = MetricsRegistry()
        
        registry.increment_counter("operations_total")
        metric = registry.get_metric("operations_total")
        
        assert metric is not None
        assert metric["value"] == 1
    
    def test_registry_reset(self):
        """Test registry reset clears metrics."""
        registry = MetricsRegistry()
        
        registry.increment_counter("operations_total")
        registry.set_gauge("plugins_active", 5.0)
        
        registry.reset()
        
        assert registry.counter("operations_total").get() == 0
        assert registry.gauge("plugins_active").get() == 0.0


class TestHealthSnapshot:
    """Test HealthSnapshot."""
    
    def test_health_snapshot_healthy(self):
        """Test health snapshot reports healthy system."""
        snapshot = HealthSnapshot(
            timestamp="2024-02-17T10:00:00Z",
            total_plugins=5,
            active_plugins=5,
            degraded_plugins=0,
            total_operations=100,
            failed_operations=2,  # 2% failure rate
        )
        
        assert snapshot.is_healthy()
        assert snapshot.failed_rate == 2.0
    
    def test_health_snapshot_unhealthy_high_failure_rate(self):
        """Test health snapshot reports unhealthy with high failure rate."""
        snapshot = HealthSnapshot(
            timestamp="2024-02-17T10:00:00Z",
            total_plugins=5,
            active_plugins=5,
            total_operations=100,
            failed_operations=20,  # 20% failure rate
        )
        
        assert not snapshot.is_healthy()
    
    def test_health_snapshot_unhealthy_crashed_plugins(self):
        """Test health snapshot reports unhealthy with crashed plugins."""
        snapshot = HealthSnapshot(
            timestamp="2024-02-17T10:00:00Z",
            total_plugins=5,
            active_plugins=4,
            crashed_plugins=["plugin_a"],
        )
        
        assert not snapshot.is_healthy()
    
    def test_health_snapshot_to_dict(self):
        """Test health snapshot converts to dict."""
        snapshot = HealthSnapshot(
            timestamp="2024-02-17T10:00:00Z",
            total_plugins=5,
            active_plugins=5,
        )
        
        data = snapshot.to_dict()
        assert data["total_plugins"] == 5
        assert data["active_plugins"] == 5


class TestHealthSnapshotCollector:
    """Test HealthSnapshotCollector."""
    
    @pytest.mark.asyncio
    async def test_collector_collect(self):
        """Test collector gathers metrics."""
        # Create mock runtime
        mock_runtime = MagicMock()
        mock_runtime.capability_registry = None
        mock_runtime.plugin_manager = MagicMock()
        mock_runtime.plugin_manager._plugins = {}
        
        collector = HealthSnapshotCollector(mock_runtime)
        snapshot = collector.collect()
        
        assert snapshot is not None
        assert snapshot.timestamp is not None
        assert snapshot.total_operations >= 0
    
    @pytest.mark.asyncio
    async def test_collector_calculates_failed_rate(self):
        """Test collector calculates failure rate."""
        mock_runtime = MagicMock()
        mock_runtime.capability_registry = None
        mock_runtime.plugin_manager = MagicMock()
        mock_runtime.plugin_manager._plugins = {}
        
        # Increment some metrics
        from core.observability.metrics import get_metrics_registry
        metrics = get_metrics_registry()
        metrics.increment_counter("operations_total")
        metrics.increment_counter("operations_total")
        metrics.increment_counter("operations_failed_total")
        
        collector = HealthSnapshotCollector(mock_runtime)
        snapshot = collector.collect()
        
        assert snapshot.total_operations >= 2
        assert snapshot.failed_operations >= 1
        assert snapshot.failed_rate >= 0


class TestMetricsGlobalSingleton:
    """Test global metrics registry singleton."""
    
    def test_global_registry_singleton(self):
        """Test get_metrics_registry returns same instance."""
        reg1 = get_metrics_registry()
        reg2 = get_metrics_registry()
        
        assert reg1 is reg2
    
    def test_global_registry_increments_persist(self):
        """Test increments persist across calls."""
        reg1 = get_metrics_registry()
        reg1.increment_counter("test_metric")
        
        reg2 = get_metrics_registry()
        assert reg2.counter("test_metric").get() >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
