"""
Security helpers for plugin SDK.

Plugins import this module instead of importing modules/core internals.
"""

from __future__ import annotations

import base64
import os
import re
from typing import Any

from cryptography.fernet import Fernet

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
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            if any(sensitive in key.lower() for sensitive in SENSITIVE_KEYS):
                result[key] = mask
            else:
                result[key] = sanitize_for_logging(value, mask)
        return result

    if isinstance(data, list):
        return [sanitize_for_logging(item, mask) for item in data]

    if isinstance(data, tuple):
        return tuple(sanitize_for_logging(item, mask) for item in data)

    if isinstance(data, str):
        if (
            "authorization" in data.lower()
            or "bearer" in data.lower()
            or "oauth" in data.lower()
        ):
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

    return data


def sanitize_headers(headers: dict[str, str]) -> dict[str, str]:
    return sanitize_for_logging(headers)


class TokenEncryption:
    """Encryption/decryption for OAuth token blobs at rest."""

    def __init__(self, key: bytes):
        self._fernet = Fernet(key)

    @classmethod
    def from_env(cls) -> "TokenEncryption":
        key_b64 = os.environ.get("OAUTH_ENCRYPTION_KEY")
        if not key_b64:
            raise RuntimeError("OAUTH_ENCRYPTION_KEY environment variable not set")

        try:
            key = base64.urlsafe_b64decode(key_b64)
            return cls(key)
        except Exception as e:
            raise RuntimeError(f"Invalid OAUTH_ENCRYPTION_KEY: {e}")

    @staticmethod
    def generate_key() -> str:
        return Fernet.generate_key().decode()

    def encrypt(self, data: dict[str, Any]) -> str:
        import json

        plaintext = json.dumps(data).encode("utf-8")
        encrypted = self._fernet.encrypt(plaintext)
        return base64.urlsafe_b64encode(encrypted).decode("ascii")

    def decrypt(self, encrypted_blob: str) -> dict[str, Any]:
        import json

        try:
            encrypted = base64.urlsafe_b64decode(encrypted_blob.encode("ascii"))
            plaintext = self._fernet.decrypt(encrypted)
            return json.loads(plaintext.decode("utf-8"))
        except Exception as e:
            raise ValueError(f"Failed to decrypt token data: {e}")


__all__ = [
    "sanitize_for_logging",
    "sanitize_headers",
    "TokenEncryption",
]
