"""
CSRF signing secret lifecycle in SecretStore.

Keys:
  runtime.csrf_secret          — active HMAC secret
  runtime.csrf_secret.previous   — previous secret (grace period after rotation)
  runtime.csrf_secret.meta       — JSON: rotated_at, previous_expires_at
"""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from modules.security.secret_store import SecretStore

CSRF_STORE_KEY = "runtime.csrf_secret"
CSRF_PREVIOUS_KEY = "runtime.csrf_secret.previous"
CSRF_META_KEY = "runtime.csrf_secret.meta"

ENV_CSRF = "CSRF_SECRET"
ENV_CSRF_PREVIOUS = "CSRF_SECRET_PREVIOUS"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def default_csrf_generator() -> str:
    return secrets.token_hex(32)


@dataclass(frozen=True)
class CsrfRotationPolicy:
    """When to auto-rotate and how long the previous secret stays valid."""

    max_age_days: int = 90
    grace_hours: int = 24

    @classmethod
    def from_env(cls) -> "CsrfRotationPolicy":
        days_raw = (os.getenv("RUNTIME_CSRF_ROTATION_DAYS") or "90").strip()
        grace_raw = (os.getenv("RUNTIME_CSRF_GRACE_HOURS") or "24").strip()
        try:
            max_age_days = int(days_raw)
        except ValueError:
            max_age_days = 90
        try:
            grace_hours = int(grace_raw)
        except ValueError:
            grace_hours = 24
        return cls(max_age_days=max(0, max_age_days), grace_hours=max(0, grace_hours))


def apply_csrf_secrets_to_env(current: str, previous: Optional[str] = None) -> None:
    os.environ[ENV_CSRF] = current
    if previous:
        os.environ[ENV_CSRF_PREVIOUS] = previous
    else:
        os.environ.pop(ENV_CSRF_PREVIOUS, None)


async def _load_meta(store: "SecretStore") -> dict:
    raw = await store.get(CSRF_META_KEY)
    if not raw:
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


async def _save_meta(store: "SecretStore", meta: dict) -> None:
    await store.put(CSRF_META_KEY, json.dumps(meta, separators=(",", ":")).encode("utf-8"))


async def load_csrf_secrets(store: "SecretStore") -> tuple[Optional[str], Optional[str]]:
    """Return (current, previous) plaintext secrets from store."""
    current_raw = await store.get(CSRF_STORE_KEY)
    previous_raw = await store.get(CSRF_PREVIOUS_KEY)
    current = current_raw.decode("utf-8") if current_raw else None
    previous = previous_raw.decode("utf-8") if previous_raw else None
    return current, previous


async def expire_csrf_previous_if_needed(store: "SecretStore") -> bool:
    """Drop previous secret when grace window ended. Returns True if cleared."""
    meta = await _load_meta(store)
    expires_at = meta.get("previous_expires_at")
    if not expires_at:
        return False
    try:
        if _utcnow() < _parse_iso(str(expires_at)):
            return False
    except ValueError:
        pass
    if await store.delete(CSRF_PREVIOUS_KEY):
        meta.pop("previous_expires_at", None)
        await _save_meta(store, meta)
        return True
    return False


async def rotate_csrf_secret(
    store: "SecretStore",
    *,
    generator: Optional[Callable[[], str]] = None,
    policy: Optional[CsrfRotationPolicy] = None,
) -> dict:
    """
    Rotate CSRF HMAC secret: current → previous, generate new current.

    Returns summary dict (rotated_at, previous_expires_at, had_previous).
    """
    gen = generator or default_csrf_generator
    pol = policy or CsrfRotationPolicy.from_env()
    now = _utcnow()

    current, _ = await load_csrf_secrets(store)
    if current:
        await store.put(CSRF_PREVIOUS_KEY, current.encode("utf-8"))

    new_secret = gen()
    await store.put(CSRF_STORE_KEY, new_secret.encode("utf-8"))

    previous_expires_at = (now + timedelta(hours=pol.grace_hours)).isoformat()
    meta = await _load_meta(store)
    meta["rotated_at"] = now.isoformat()
    if current:
        meta["previous_expires_at"] = previous_expires_at
    else:
        meta.pop("previous_expires_at", None)
    await _save_meta(store, meta)

    previous_for_env = current if current else None
    apply_csrf_secrets_to_env(new_secret, previous_for_env)

    return {
        "rotated_at": meta["rotated_at"],
        "previous_expires_at": meta.get("previous_expires_at"),
        "had_previous": bool(current),
    }


async def maybe_auto_rotate_csrf_secret(
    store: "SecretStore",
    *,
    policy: Optional[CsrfRotationPolicy] = None,
    readonly: bool = False,
    generator: Optional[Callable[[], str]] = None,
) -> Optional[dict]:
    """
    Auto-rotate when secret age exceeds policy.max_age_days.
    max_age_days=0 disables auto rotation.
    Returns rotation summary if rotated, else None.
    """
    pol = policy or CsrfRotationPolicy.from_env()
    if pol.max_age_days <= 0 or readonly:
        return None

    await expire_csrf_previous_if_needed(store)

    current, previous = await load_csrf_secrets(store)
    if not current:
        return None

    meta = await _load_meta(store)
    rotated_at = meta.get("rotated_at")
    if not rotated_at:
        # Legacy secret without metadata — stamp now, rotate on next cycle.
        meta["rotated_at"] = _utcnow().isoformat()
        await _save_meta(store, meta)
        return None

    try:
        age = _utcnow() - _parse_iso(str(rotated_at))
    except ValueError:
        age = timedelta(days=pol.max_age_days + 1)

    if age < timedelta(days=pol.max_age_days):
        return None

    return await rotate_csrf_secret(store, generator=generator, policy=pol)


async def sync_csrf_secrets_to_env(store: "SecretStore") -> None:
    """Load store keys into os.environ (after bootstrap / rotation)."""
    await expire_csrf_previous_if_needed(store)
    current, previous = await load_csrf_secrets(store)
    if current:
        apply_csrf_secrets_to_env(current, previous)
