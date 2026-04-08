"""
Rate Limiter — per-plugin rate enforcement.

Token bucket algorithm for distributed rate limiting.
Thread-safe with automatic token refill.
"""

import time
import threading
from typing import Dict, Tuple
from dataclasses import dataclass, field


@dataclass
class TokenBucket:
    """Token bucket for rate limiting."""
    capacity: float
    refill_rate: float  # tokens per second
    tokens: float = field(default=0.0)  # Will be set in __post_init__
    last_refill: float = field(default=0.0)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    
    def __post_init__(self):
        """Initialize."""
        self.tokens = self.capacity
        self.last_refill = time.time()
    
    def try_consume(self, amount: float = 1.0) -> bool:
        """Try to consume tokens. Returns True if successful, False if rate limited."""
        with self._lock:
            # Refill tokens based on time elapsed
            now = time.time()
            elapsed = now - self.last_refill
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
            self.last_refill = now
            
            # Try to consume
            if self.tokens >= amount:
                self.tokens -= amount
                return True
            return False
    
    def get_available_tokens(self) -> float:
        """Get current token count."""
        with self._lock:
            now = time.time()
            elapsed = now - self.last_refill
            return min(self.capacity, self.tokens + elapsed * self.refill_rate)


class PluginRateLimiter:
    """
    Rate limiter for per-plugin call limits.
    
    Uses token bucket algorithm.
    Thread-safe with per-plugin tracking.
    """
    
    def __init__(self):
        """Initialize rate limiter."""
        self._buckets: Dict[str, TokenBucket] = {}
        self._lock = threading.Lock()
    
    def set_limit(self, plugin_name: str, calls_per_minute: int) -> None:
        """Set rate limit for a plugin."""
        if calls_per_minute <= 0:
            return  # No limit
        
        with self._lock:
            # Token bucket: calls_per_minute tokens, refill at rate per second
            capacity = float(calls_per_minute)
            refill_rate = calls_per_minute / 60.0  # tokens per second
            self._buckets[plugin_name] = TokenBucket(
                capacity=capacity,
                refill_rate=refill_rate
            )
    
    def try_call(self, plugin_name: str) -> bool:
        """Try to make a call to plugin. Returns True if allowed, False if rate limited."""
        with self._lock:
            if plugin_name not in self._buckets:
                return True  # No limit set, allow
            
            bucket = self._buckets[plugin_name]
        
        # Release lock before consuming (to avoid holding lock during slow operations)
        return bucket.try_consume(1.0)
    
    def get_status(self, plugin_name: str) -> Dict[str, float]:
        """Get rate limit status for a plugin."""
        with self._lock:
            if plugin_name not in self._buckets:
                return {"limited": False}
            
            bucket = self._buckets[plugin_name]
        
        return {
            "limited": True,
            "capacity": bucket.capacity,
            "refill_rate": bucket.refill_rate,
            "available_tokens": bucket.get_available_tokens(),
            "calls_per_minute": int(bucket.capacity),
        }
    
    def reset(self) -> None:
        """Reset all limits (for testing)."""
        with self._lock:
            self._buckets.clear()
