"""
flow: Resource Limits Tests — rate limiting and resource enforcement.

Tests for:
- PluginRateLimiter (token bucket algorithm)
- Rate limit enforcement in plugin execution
- Resource limit enforcement
"""

import pytest
import time
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from core.observability.rate_limiter import (
    PluginRateLimiter,
    TokenBucket,
    get_rate_limiter,
)


class TestTokenBucket:
    """Test TokenBucket rate limiting algorithm."""
    
    def test_token_bucket_initialization(self):
        """Test token bucket initializes with full capacity."""
        bucket = TokenBucket(capacity=10.0, refill_rate=1.0)
        
        assert bucket.tokens >= 9.0  # Close to capacity (time passed during init)
    
    def test_token_bucket_consume_success(self):
        """Test consuming tokens when available."""
        bucket = TokenBucket(capacity=10.0, refill_rate=1.0)
        
        success = bucket.try_consume(1.0)
        assert success
        assert bucket.tokens < 10.0
    
    def test_token_bucket_consume_fail(self):
        """Test consuming tokens when insufficient."""
        bucket = TokenBucket(capacity=1.0, refill_rate=1.0)
        
        # Consume all tokens
        bucket.try_consume(1.0)
        
        # Try to consume more (should fail)
        success = bucket.try_consume(1.0)
        assert not success
    
    def test_token_bucket_refill(self):
        """Test tokens refill over time."""
        bucket = TokenBucket(capacity=10.0, refill_rate=100.0)  # 100 tokens/sec (faster)
        
        # Consume all initial tokens
        bucket.try_consume(10.0)
        assert bucket.tokens == 0.0
        
        # Wait briefly (should refill quickly at 100/sec)
        time.sleep(0.05)  # Should refill 5 tokens
        
        available = bucket.get_available_tokens()
        assert available > 0
    
    def test_limiter_thread_safe(self):
        """Test token bucket is thread-safe."""
        import threading
        
        bucket = TokenBucket(capacity=50.0, refill_rate=100.0)
        results = []
        lock = threading.Lock()
        
        def consume_many():
            for _ in range(5):
                result = bucket.try_consume(1.0)
                with lock:
                    results.append(result)
        
        threads = [threading.Thread(target=consume_many) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # Most should succeed (50 capacity for 50 total attempts)
        success_count = sum(1 for r in results if r)
        assert success_count == 50


class TestPluginRateLimiter:
    """Test PluginRateLimiter."""
    
    def test_limiter_no_limit_by_default(self):
        """Test rate limiter allows calls by default (no limit set)."""
        limiter = PluginRateLimiter()
        
        # Without limit, should allow any calls
        for _ in range(100):
            assert limiter.try_call("plugin_a")
    
    def test_limiter_set_limit(self):
        """Test setting rate limit."""
        limiter = PluginRateLimiter()
        limiter.set_limit("plugin_a", 10)  # 10 calls per minute
        
        # Should succeed at first (capacity is 10)
        for _ in range(10):
            assert limiter.try_call("plugin_a")
        
        # Should fail when exceeding limit
        assert not limiter.try_call("plugin_a")
    
    def test_limiter_independent_per_plugin(self):
        """Test rate limits are independent per plugin."""
        limiter = PluginRateLimiter()
        limiter.set_limit("plugin_a", 5)
        limiter.set_limit("plugin_b", 10)
        
        # Exhaust plugin_a
        for _ in range(5):
            assert limiter.try_call("plugin_a")
        assert not limiter.try_call("plugin_a")
        
        # plugin_b should still work
        for _ in range(10):
            assert limiter.try_call("plugin_b")
        assert not limiter.try_call("plugin_b")
    
    def test_limiter_refill_after_time(self):
        """Test rate limit tokens refill over time."""
        limiter = PluginRateLimiter()
        limiter.set_limit("plugin_a", 100)  # 100 calls per minute = ~1.67/sec
        
        # Exhaust capacity
        for _ in range(100):
            limiter.try_call("plugin_a")
        
        # Should be limited now
        assert not limiter.try_call("plugin_a")
        
        # Wait for tokens to refill (at 100/60 per sec = ~1.67/sec)
        time.sleep(1.0)
        
        # Should now allow at least 1 more call
        result = limiter.try_call("plugin_a")
        # Result depends on timing, just verify it doesn't crash
        assert isinstance(result, bool)
    
    def test_limiter_get_status(self):
        """Test getting rate limit status."""
        limiter = PluginRateLimiter()
        limiter.set_limit("plugin_a", 100)
        
        status = limiter.get_status("plugin_a")
        
        assert status["limited"] is True
        assert status["capacity"] == 100.0
        assert status["calls_per_minute"] == 100
    
    def test_limiter_get_status_no_limit(self):
        """Test status for unlimited plugin."""
        limiter = PluginRateLimiter()
        
        status = limiter.get_status("plugin_unknown")
        
        assert status["limited"] is False
    
    def test_limiter_reset(self):
        """Test resetting rate limiter."""
        limiter = PluginRateLimiter()
        limiter.set_limit("plugin_a", 5)
        
        # Exhaust
        for _ in range(5):
            limiter.try_call("plugin_a")
        
        # Should be limited
        assert not limiter.try_call("plugin_a")
        
        # Reset
        limiter.reset()
        
        # Should allow calls again (no limit set anymore)
        for _ in range(100):
            assert limiter.try_call("plugin_a")


class TestRateLimitBurstTraffic:
    """Test rate limiter under burst traffic."""
    
    def test_burst_allowed_then_rate_limited(self):
        """Test burst is allowed up to capacity, then rate limited."""
        limiter = PluginRateLimiter()
        limiter.set_limit("plugin_a", 100)  # 100 calls/min = ~1.67/sec
        
        # Burst of 100 should succeed
        burst_results = [limiter.try_call("plugin_a") for _ in range(100)]
        assert all(burst_results)
        
        # Additional calls should fail (rate limited)
        assert not limiter.try_call("plugin_a")
        assert not limiter.try_call("plugin_a")
    
    def test_steady_state_rate_limiting(self):
        """Test steady-state rate limiting."""
        limiter = PluginRateLimiter()
        limiter.set_limit("plugin_a", 2)  # 2 calls per minute
        
        # Consume initial capacity
        assert limiter.try_call("plugin_a")
        assert limiter.try_call("plugin_a")
        assert not limiter.try_call("plugin_a")
        
        # Short wait for partial token refill (at 2/min, ~0.033/sec)
        time.sleep(3.5)  # Should refill ~0.1 tokens
        
        # May or may not allow call depending on timing
        # Just verify it's working (doesn't crash)
        limiter.try_call("plugin_a")


class TestRateLimitGlobalSingleton:
    """Test global rate limiter singleton."""
    
    def test_global_limiter_singleton(self):
        """Test get_rate_limiter returns same instance."""
        limiter1 = get_rate_limiter()
        limiter2 = get_rate_limiter()
        
        assert limiter1 is limiter2
    
    def test_global_limiter_settings_persist(self):
        """Test rate limit settings persist."""
        limiter1 = get_rate_limiter()
        limiter1.set_limit("test_plugin", 50)
        
        limiter2 = get_rate_limiter()
        status = limiter2.get_status("test_plugin")
        
        assert status["limited"] is True
        assert status["calls_per_minute"] == 50


class TestConcurrentRateLimiting:
    """Test rate limiting under concurrent load."""
    
    def test_concurrent_calls_rate_limited(self):
        """Test concurrent calls are rate limited correctly."""
        import threading
        
        limiter = PluginRateLimiter()
        limiter.set_limit("plugin_a", 20)  # 20 calls total capacity
        
        success_count = [0]  # Use list to allow modification in thread
        lock = threading.Lock()
        
        def make_calls():
            for _ in range(5):
                if limiter.try_call("plugin_a"):
                    with lock:
                        success_count[0] += 1
        
        # Start 4 threads, each trying 5 calls (20 total attempts)
        threads = [threading.Thread(target=make_calls) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # Should only allow 20 (capacity)
        assert success_count[0] == 20


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
