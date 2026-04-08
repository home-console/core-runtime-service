"""CSRF protection for admin API endpoints."""

import os
import hmac
import hashlib
from typing import Dict, List


class CSRFProtection:
    """
    CSRF token generation and validation.

    Token format: HMAC-SHA256(secret, session_id)
    """

    def __init__(self, secret: bytes):
        self._secret = secret

    @classmethod
    def from_env(cls) -> "CSRFProtection":
        secret = os.environ.get("CSRF_SECRET")
        if not secret:
            raise RuntimeError(
                "CSRF_SECRET environment variable not set. "
                "Generate one with: python -c 'import secrets; print(secrets.token_hex(32))'"
            )
        return cls(secret.encode("utf-8"))

    def generate_token(self, session_id: str) -> str:
        mac = hmac.new(self._secret, session_id.encode("utf-8"), hashlib.sha256)
        return mac.hexdigest()

    def validate_token(self, token: str, session_id: str) -> None:
        expected = self.generate_token(session_id)
        if not hmac.compare_digest(token, expected):
            raise ValueError("Invalid CSRF token")


class RateLimiter:
    """Simple in-memory rate limiter with sliding window."""

    def __init__(self):
        self._windows: Dict[str, Dict[str, List[float]]] = {}

    def check_limit(self, endpoint: str, identifier: str, max_calls: int, window_sec: int) -> None:
        import time

        now = time.time()
        key = f"{endpoint}:{identifier}"

        if endpoint not in self._windows:
            self._windows[endpoint] = {}

        if key not in self._windows[endpoint]:
            self._windows[endpoint][key] = []

        timestamps = self._windows[endpoint][key]
        timestamps[:] = [ts for ts in timestamps if now - ts < window_sec]

        if len(timestamps) >= max_calls:
            raise ValueError(f"Rate limit exceeded: max {max_calls} calls per {window_sec}s")

        timestamps.append(now)

    def reset(self, endpoint: str, identifier: str) -> None:
        key = f"{endpoint}:{identifier}"
        if endpoint in self._windows and key in self._windows[endpoint]:
            del self._windows[endpoint][key]
