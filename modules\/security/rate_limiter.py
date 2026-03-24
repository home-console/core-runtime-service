"""
In-memory rate limiter for API endpoints (sliding window).
"""

from typing import Dict


class RateLimiter:
    """
    Simple in-memory rate limiter.

    CRITICAL: Admin API endpoints MUST be rate-limited.

    Uses sliding window algorithm with in-memory storage.
    NOT suitable for multi-instance deployments (use Redis for that).

    Usage:
        limiter = RateLimiter()
        limiter.check_limit("admin_sync", identifier="user123", max_calls=5, window_sec=60)
    """

    def __init__(self):
        """Initialize rate limiter."""
        self._windows: Dict[str, Dict[str, list]] = {}

    def check_limit(
        self,
        endpoint: str,
        identifier: str,
        max_calls: int,
        window_sec: int,
    ) -> None:
        """
        Check if rate limit exceeded.

        Args:
            endpoint: Endpoint name (e.g., "admin_sync")
            identifier: User/IP identifier
            max_calls: Maximum calls allowed in window
            window_sec: Time window in seconds

        Raises:
            ValueError: If rate limit exceeded
        """
        import time

        now = time.time()
        key = f"{endpoint}:{identifier}"

        if endpoint not in self._windows:
            self._windows[endpoint] = {}

        if key not in self._windows[endpoint]:
            self._windows[endpoint][key] = []

        # Remove old timestamps outside window
        timestamps = self._windows[endpoint][key]
        timestamps[:] = [ts for ts in timestamps if now - ts < window_sec]

        # Check limit
        if len(timestamps) >= max_calls:
            raise ValueError(
                f"Rate limit exceeded: max {max_calls} calls per {window_sec}s"
            )

        # Add current timestamp
        timestamps.append(now)

    def reset(self, endpoint: str, identifier: str) -> None:
        """Reset rate limit for endpoint/identifier."""
        key = f"{endpoint}:{identifier}"
        if endpoint in self._windows and key in self._windows[endpoint]:
            del self._windows[endpoint][key]
