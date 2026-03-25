"""
Health monitoring for remote capability providers.

Tracks:
- Consecutive failures
- Health status changes
- Auto-recovery timing
- Failure statistics
"""

import time
from typing import Dict, Optional
from core.capability_protocol import (
    ProviderHealthStatus,
    HEALTH_CHECK_FAILURE_THRESHOLD,
    HEALTH_CHECK_RETRY_INTERVAL,
)


class ProviderHealthMonitor:
    """
    Tracks health of remote capability providers.
    
    Automatically marks providers unhealthy after N consecutive failures.
    Periodically retries unhealthy providers.
    """
    
    def __init__(self):
        # provider_name -> ProviderHealthStatus
        self._health_status: Dict[str, ProviderHealthStatus] = {}
    
    def initialize_provider(self, provider_name: str, version: Optional[str] = None) -> None:
        """Initialize health tracking for a provider."""
        if provider_name not in self._health_status:
            self._health_status[provider_name] = ProviderHealthStatus(
                provider_name=provider_name,
                healthy=True,
                last_check_time=time.time(),
                consecutive_failures=0,
                last_error=None,
                version=version,
            )
    
    def get_status(self, provider_name: str) -> ProviderHealthStatus:
        """Get current health status of provider."""
        if provider_name not in self._health_status:
            self.initialize_provider(provider_name)
        return self._health_status[provider_name]
    
    def record_success(self, provider_name: str) -> None:
        """Record successful operation."""
        status = self.get_status(provider_name)
        
        # Reset failure count
        status.consecutive_failures = 0
        
        # Mark healthy if was unhealthy
        if not status.healthy:
            status.healthy = True
            status.last_error = None
    
    def record_failure(self, provider_name: str, error_message: str) -> None:
        """Record failed operation."""
        status = self.get_status(provider_name)
        
        status.consecutive_failures += 1
        status.last_error = error_message
        status.last_check_time = time.time()
        
        # Mark unhealthy after threshold
        if status.consecutive_failures >= HEALTH_CHECK_FAILURE_THRESHOLD:
            status.healthy = False
    
    def mark_healthy(self, provider_name: str, version: Optional[str] = None) -> None:
        """Mark provider as explicitly healthy (e.g., from manifest check)."""
        status = self.get_status(provider_name)
        status.healthy = True
        status.consecutive_failures = 0
        status.last_error = None
        status.last_check_time = time.time()
        if version:
            status.version = version
    
    def mark_unhealthy(self, provider_name: str, reason: str) -> None:
        """Mark provider as explicitly unhealthy."""
        status = self.get_status(provider_name)
        status.healthy = False
        status.last_error = reason
        status.last_check_time = time.time()
    
    def get_healthy_providers(self, provider_names: list) -> list:
        """Filter list to only healthy providers."""
        return [
            name for name in provider_names
            if self.get_status(name).healthy
        ]
    
    def should_skip_provider(self, provider_name: str) -> bool:
        """Should this provider be skipped for new operations?"""
        return self.get_status(provider_name).should_skip()
    
    def should_retry_health_check(self, provider_name: str) -> bool:
        """Should health be rechecked for this provider?"""
        return self.get_status(provider_name).should_retry_check(
            HEALTH_CHECK_RETRY_INTERVAL
        )
    
    def get_all_statuses(self) -> Dict[str, ProviderHealthStatus]:
        """Get all provider health statuses."""
        return dict(self._health_status)
    
    def get_summary(self) -> Dict[str, int]:
        """Get summary of health state."""
        healthy_count = sum(1 for s in self._health_status.values() if s.healthy)
        unhealthy_count = len(self._health_status) - healthy_count
        
        return {
            "total_providers": len(self._health_status),
            "healthy": healthy_count,
            "unhealthy": unhealthy_count,
        }


# Backward-compat alias (class was renamed from HealthMonitor to ProviderHealthMonitor)
HealthMonitor = ProviderHealthMonitor
