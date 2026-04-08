"""
Health Snapshot — system health summary.

Provides comprehensive view of system state:
- plugin counts (total, active, degraded)
- operation metrics (total, failed)
- provider status
"""

import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.exception_groups import BEST_EFFORT_BACKGROUND_ERRORS

logger = logging.getLogger(__name__)


@dataclass
class ProviderStatusSummary:
    """Status of a single provider."""
    name: str
    type: str  # "local", "remote", "container", "process"
    status: str  # "healthy", "degraded", "unavailable"
    last_error: Optional[str] = None
    failure_count: int = 0
    success_count: int = 0


@dataclass
class HealthSnapshot:
    """System health snapshot."""
    timestamp: str
    
    # Plugin metrics
    total_plugins: int = 0
    active_plugins: int = 0
    degraded_plugins: int = 0
    crashed_plugins: List[str] = None
    
    # Operation metrics
    total_operations: int = 0
    failed_operations: int = 0
    failed_rate: float = 0.0  # percentage
    
    # Provider status
    provider_status_summary: Optional[Dict[str, ProviderStatusSummary]] = None
    
    # Execution mode breakdown
    execution_modes: Dict[str, int] = None  # {"in_process": 5, "remote": 2, ...}
    
    # Recent errors
    recent_errors: List[Dict[str, Any]] = None
    
    def __post_init__(self):
        """Initialize default values."""
        if self.crashed_plugins is None:
            self.crashed_plugins = []
        if self.provider_status_summary is None:
            self.provider_status_summary = {}
        if self.execution_modes is None:
            self.execution_modes = {}
        if self.recent_errors is None:
            self.recent_errors = []
        
        # Calculate failed rate
        if self.total_operations > 0:
            self.failed_rate = (self.failed_operations / self.total_operations) * 100
    
    def is_healthy(self) -> bool:
        """Check if system is healthy."""
        # System is unhealthy if:
        # - More than 10% operations failing
        # - Any crashed plugins
        # - Unavailable providers
        if self.failed_rate > 10:
            return False
        if self.crashed_plugins:
            return False
        
        unavailable_providers = [
            p for p in self.provider_status_summary.values()
            if p.status == "unavailable"
        ]
        if unavailable_providers:
            return False
        
        return True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict, handling nested dataclasses."""
        result = asdict(self)
        result["provider_status_summary"] = {
            name: asdict(status)
            for name, status in (self.provider_status_summary or {}).items()
        }
        return result


class HealthSnapshotCollector:
    """Collects system health snapshot from various sources."""
    
    def __init__(self, runtime: Any):
        """Initialize collector."""
        self.runtime = runtime
        # Metrics registry injected from runtime (no global singleton)
        self._metrics = getattr(runtime, "_metrics_registry", None)

    def collect(self) -> HealthSnapshot:
        """Collect current system health snapshot."""
        # Use injected metrics registry if available
        metrics = self._metrics
        if metrics is None:
            # Fallback: create new registry (shouldn't happen in normal operation)
            from core.observability.metrics import MetricsRegistry
            metrics = MetricsRegistry()
        
        all_metrics = metrics.get_all_metrics()
        
        # Extract metrics
        operations_total = all_metrics.get("counters", {}).get("operations_total", {}).get("value", 0)
        operations_failed = all_metrics.get("counters", {}).get("operations_failed_total", {}).get("value", 0)
        
        plugin_load_total = all_metrics.get("counters", {}).get("plugin_load_total", {}).get("value", 0)
        plugin_crash_total = all_metrics.get("counters", {}).get("plugin_crash_total", {}).get("value", 0)
        plugins_active = all_metrics.get("gauges", {}).get("plugins_active", 0)
        
        provider_failures = all_metrics.get("counters", {}).get("provider_failures_total", {}).get("value", 0)
        provider_success = all_metrics.get("counters", {}).get("provider_success_total", {}).get("value", 0)
        provider_degraded = all_metrics.get("gauges", {}).get("provider_health_degraded", 0)
        
        # Build snapshot
        snapshot = HealthSnapshot(
            timestamp=datetime.now(timezone.utc).isoformat() + "Z",
            total_plugins=plugin_load_total,
            active_plugins=max(0, int(plugins_active)),
            degraded_plugins=int(provider_degraded),
            total_operations=operations_total,
            failed_operations=operations_failed,
            provider_status_summary={},
            execution_modes={},
        )
        
        # Calculate failed rate
        if snapshot.total_operations > 0:
            snapshot.failed_rate = (snapshot.failed_operations / snapshot.total_operations) * 100
        
        # Collect provider status from capability registry
        if hasattr(self.runtime, 'capability_registry') and self.runtime.capability_registry:
            try:
                cap_reg = self.runtime.capability_registry
                all_providers = cap_reg.get_all_providers_for_capability("*")  # Get all
                
                provider_statuses: Dict[str, ProviderStatusSummary] = {}
                for provider_dict in (all_providers or []):
                    provider_name = provider_dict.get("plugin")
                    provider_type = provider_dict.get("execution_mode", "unknown")
                    
                    # Determine status based on failure/success rates
                    total_calls = provider_dict.get("success_count", 0) + provider_dict.get("failure_count", 0)
                    if total_calls == 0:
                        status = "healthy"
                    else:
                        failure_rate = provider_dict.get("failure_count", 0) / total_calls
                        if failure_rate > 0.5:
                            status = "unavailable"
                        elif failure_rate > 0.2:
                            status = "degraded"
                        else:
                            status = "healthy"
                    
                    provider_statuses[provider_name] = ProviderStatusSummary(
                        name=provider_name,
                        type=provider_type,
                        status=status,
                        failure_count=provider_dict.get("failure_count", 0),
                        success_count=provider_dict.get("success_count", 0),
                    )
                
                snapshot.provider_status_summary = provider_statuses
            except BEST_EFFORT_BACKGROUND_ERRORS as e:
                if isinstance(e, (TypeError, KeyError, AttributeError, ValueError)):
                    logger.debug(
                        "HealthSnapshot: provider status (introspection): %s",
                        e,
                        exc_info=True,
                    )
                else:
                    logger.debug(
                        "HealthSnapshot: failed to collect provider status (unexpected)",
                        exc_info=True,
                    )
        
        # Collect execution modes
        try:
            if hasattr(self.runtime, 'plugin_manager') and self.runtime.plugin_manager:
                pm = self.runtime.plugin_manager
                if hasattr(pm, '_plugins'):
                    for plugin_name, plugin_instance in (pm._plugins or {}).items():
                        if hasattr(plugin_instance, 'metadata'):
                            meta = plugin_instance.metadata
                            mode = getattr(meta, 'execution_mode', 'in_process')
                            snapshot.execution_modes[mode] = snapshot.execution_modes.get(mode, 0) + 1
        except BEST_EFFORT_BACKGROUND_ERRORS as e:
            if isinstance(e, (TypeError, KeyError, AttributeError, ValueError)):
                logger.debug(
                    "HealthSnapshot: execution modes (introspection): %s",
                    e,
                    exc_info=True,
                )
            else:
                logger.debug(
                    "HealthSnapshot: failed to collect execution modes (unexpected)",
                    exc_info=True,
                )
        
        return snapshot
