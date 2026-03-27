"""
Security utilities for Home Console.

CRITICAL P0 security components:
- Log sanitization (remove secrets from logs)
- Token encryption for storage
- Security headers and constants
"""

import base64
import hashlib
import os
import re
from typing import Any, Dict

from cryptography.fernet import Fernet

# ============================
# LOG SANITIZATION
# ============================

# Sensitive keys that must be sanitized in logs
SENSITIVE_KEYS = {
    "access_token",
    "refresh_token",
    "client_secret",
    "authorization",
    "cookie",
    "password",
    "x-token",
    "x_token",
    "api_key",
    "secret",
    "token",
    "auth",
}


def sanitize_for_logging(data: Any, mask: str = "***REDACTED***") -> Any:
    """
    Recursively sanitize sensitive data for logging.

    CRITICAL: This function MUST be called before any logging operation
    that might contain user data, tokens, or secrets.

    Args:
        data: Any data structure (dict, list, str, etc.)
        mask: String to replace sensitive values with

    Returns:
        Sanitized copy of data with sensitive values masked

    Examples:
        >>> sanitize_for_logging({"access_token": "secret123"})
        {"access_token": "***REDACTED***"}

        >>> sanitize_for_logging({"user": "john", "password": "pass123"})
        {"user": "john", "password": "***REDACTED***"}
    """
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            # Check if key is sensitive (case-insensitive)
            if any(sensitive in key.lower() for sensitive in SENSITIVE_KEYS):
                result[key] = mask
            else:
                result[key] = sanitize_for_logging(value, mask)
        return result

    elif isinstance(data, list):
        return [sanitize_for_logging(item, mask) for item in data]

    elif isinstance(data, tuple):
        return tuple(sanitize_for_logging(item, mask) for item in data)

    elif isinstance(data, str):
        # Sanitize authorization headers in strings
        # Pattern: "Authorization: Bearer <token>" or "OAuth <token>"
        if (
            "authorization" in data.lower()
            or "bearer" in data.lower()
            or "oauth" in data.lower()
        ):
            # Replace token-like patterns (long alphanumeric strings)
            data = re.sub(
                r"(bearer|oauth)\s+[a-zA-Z0-9_\-\.]+",
                r"\1 ***REDACTED***",
                data,
                flags=re.IGNORECASE,
            )
            data = re.sub(
                r"authorization:\s*[^\s]+",
                "authorization: ***REDACTED***",
                data,
                flags=re.IGNORECASE,
            )
        return data

    else:
        # Primitive types (int, float, bool, None) - return as is
        return data


def sanitize_headers(headers: Dict[str, str]) -> Dict[str, str]:
    """
    Sanitize HTTP headers for logging.

    Args:
        headers: Dict of HTTP headers

    Returns:
        Sanitized headers dict
    """
    return sanitize_for_logging(headers)


# ============================
# TOKEN ENCRYPTION
# ============================


class TokenEncryption:
    """
    Encryption/decryption for OAuth tokens at rest.

    CRITICAL: Tokens MUST be encrypted before storing in database.
    Uses Fernet (symmetric encryption) with key from environment.

    Key management:
    - OAUTH_ENCRYPTION_KEY env variable (base64-encoded Fernet key)
    - If not set, system will fail-fast on startup
    - Key rotation: generate new key, re-encrypt all tokens

    Usage:
        encryptor = TokenEncryption.from_env()
        encrypted = encryptor.encrypt({"access_token": "...", "refresh_token": "..."})
        decrypted = encryptor.decrypt(encrypted)
    """

    def __init__(self, key: bytes):
        """
        Initialize with encryption key.

        Args:
            key: 32-byte key for Fernet encryption
        """
        self._fernet = Fernet(key)

    @classmethod
    def from_env(cls) -> "TokenEncryption":
        """
        Create TokenEncryption from OAUTH_ENCRYPTION_KEY environment variable.

        Returns:
            TokenEncryption instance

        Raises:
            RuntimeError: If OAUTH_ENCRYPTION_KEY not set or invalid
        """
        key_b64 = os.environ.get("OAUTH_ENCRYPTION_KEY")
        if not key_b64:
            raise RuntimeError(
                "OAUTH_ENCRYPTION_KEY environment variable not set. "
                "Generate one with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
            )

        try:
            key = base64.urlsafe_b64decode(key_b64)
            return cls(key)
        except Exception as e:
            raise RuntimeError(f"Invalid OAUTH_ENCRYPTION_KEY: {e}")

    @staticmethod
    def generate_key() -> str:
        """
        Generate a new Fernet encryption key.

        Returns:
            Base64-encoded key suitable for OAUTH_ENCRYPTION_KEY env variable
        """
        return Fernet.generate_key().decode()

    def encrypt(self, data: Dict[str, Any]) -> str:
        """
        Encrypt token data for storage.

        Args:
            data: Dict containing tokens (access_token, refresh_token, etc.)

        Returns:
            Encrypted blob as base64 string
        """
        import json

        plaintext = json.dumps(data).encode("utf-8")
        encrypted = self._fernet.encrypt(plaintext)
        return base64.urlsafe_b64encode(encrypted).decode("ascii")

    def decrypt(self, encrypted_blob: str) -> Dict[str, Any]:
        """
        Decrypt token data from storage.

        Args:
            encrypted_blob: Base64-encoded encrypted data

        Returns:
            Decrypted token data dict

        Raises:
            ValueError: If decryption fails (invalid key or corrupted data)
        """
        import json

        try:
            encrypted = base64.urlsafe_b64decode(encrypted_blob.encode("ascii"))
            plaintext = self._fernet.decrypt(encrypted)
            return json.loads(plaintext.decode("utf-8"))
        except Exception as e:
            raise ValueError(f"Failed to decrypt token data: {e}")


# ============================
# CSRF PROTECTION
# ============================


class CSRFProtection:
    """
    CSRF token generation and validation.

    CRITICAL: Admin API endpoints MUST validate CSRF tokens.

    Token format: HMAC-SHA256(secret, session_id)
    - secret: from CSRF_SECRET env variable
    - session_id: user session identifier

    Usage:
        csrf = CSRFProtection.from_env()
        token = csrf.generate_token(session_id="user123")
        csrf.validate_token(token, session_id="user123")  # raises if invalid
    """

    def __init__(self, secret: bytes):
        """
        Initialize with CSRF secret.

        Args:
            secret: Secret key for HMAC
        """
        self._secret = secret

    @classmethod
    def from_env(cls) -> "CSRFProtection":
        """
        Create CSRFProtection from CSRF_SECRET environment variable.

        Returns:
            CSRFProtection instance

        Raises:
            RuntimeError: If CSRF_SECRET not set
        """
        secret = os.environ.get("CSRF_SECRET")
        if not secret:
            raise RuntimeError(
                "CSRF_SECRET environment variable not set. "
                "Generate one with: python -c 'import secrets; print(secrets.token_hex(32))'"
            )
        return cls(secret.encode("utf-8"))

    def generate_token(self, session_id: str) -> str:
        """
        Generate CSRF token for session.

        Args:
            session_id: User session identifier

        Returns:
            CSRF token (hex-encoded HMAC)
        """
        import hmac

        mac = hmac.new(self._secret, session_id.encode("utf-8"), hashlib.sha256)
        return mac.hexdigest()

    def validate_token(self, token: str, session_id: str) -> None:
        """
        Validate CSRF token for session.

        Args:
            token: CSRF token from request
            session_id: User session identifier

        Raises:
            ValueError: If token is invalid
        """
        expected = self.generate_token(session_id)
        import hmac

        if not hmac.compare_digest(token, expected):
            raise ValueError("Invalid CSRF token")


# ============================
# RATE LIMITING
# ============================


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
        self, endpoint: str, identifier: str, max_calls: int, window_sec: int
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


# ============================
# SECURITY INITIALIZATION
# ============================


def check_security_env() -> Dict[str, str]:
    """
    Check that all required security environment variables are set.

    CRITICAL: Call this during runtime initialization.
    System MUST fail-fast if security environment is incomplete.

    Returns:
        Dict of warnings/errors

    Raises:
        RuntimeError: If critical env variables missing
    """
    errors = []
    warnings = []

    # Check OAuth encryption key
    if not os.environ.get("OAUTH_ENCRYPTION_KEY"):
        errors.append(
            "OAUTH_ENCRYPTION_KEY not set - tokens will be stored in plaintext"
        )

    # Check CSRF secret
    if not os.environ.get("CSRF_SECRET"):
        errors.append("CSRF_SECRET not set - admin API vulnerable to CSRF")

    # Check OAuth secrets not hardcoded
    yandex_client_secret = os.environ.get("YANDEX_CLIENT_SECRET")
    if not yandex_client_secret:
        warnings.append(
            "YANDEX_CLIENT_SECRET not set - using hardcoded secret (INSECURE)"
        )

    if errors:
        raise RuntimeError(
            "Security environment check failed:\n"
            + "\n".join(f"  - {e}" for e in errors)
            + "\n\nSystem will NOT start without proper security configuration."
        )

    return {"errors": errors, "warnings": warnings}
