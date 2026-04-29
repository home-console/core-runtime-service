"""
Shared domain: risk models.

Важно: этот модуль не должен импортировать ничего из modules.security или modules.credentials.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class RiskAction(str, Enum):
    """Risk-based decision action."""

    ALLOW = "allow"
    REQUIRE_MFA = "require_mfa"
    TEMP_BLOCK = "temporary_block"
    FREEZE = "freeze"


class EventType(str, Enum):
    """Event types contributing to risk score."""

    SECRET_READ = "secret_read"
    SECRET_READ_SPIKE = "secret_read_spike"
    SECRET_READ_BURST = "secret_read_burst"

    MFA_SUCCESS = "mfa_success"
    MFA_FAILURE = "mfa_failure"
    MFA_BRUTE_FORCE = "mfa_brute_force"

    ACCESS_ALLOWED = "access_allowed"
    ACCESS_DENIED = "access_denied"

    ACCOUNT_FROZEN = "account_frozen"
    ACCOUNT_UNFROZEN = "account_unfrozen"

    ELEVATION_CREATED = "elevation_created"
    ELEVATION_EXPIRED = "elevation_expired"


@dataclass(frozen=True)
class RiskEvent:
    """Immutable event contributing to user's risk score."""

    user_id: str
    event_type: EventType
    weight: float
    timestamp: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not -100 <= self.weight <= 100:
            raise ValueError(f"weight must be in [-100, 100], got {self.weight}")

    def age_seconds(self, current_time: float) -> float:
        return max(0, current_time - self.timestamp)


@dataclass(frozen=True)
class RiskAssessment:
    """Result of risk assessment."""

    score: float
    action: RiskAction
    reasons: list[str] = field(default_factory=list)
    events_considered: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def __post_init__(self):
        if not 0 <= self.score <= 100:
            raise ValueError(f"score must be in [0, 100], got {self.score}")


@dataclass
class RiskConfig:
    """Configuration for risk engine."""

    window_seconds: int = 300
    decay_half_life: int = 60
    max_events_per_user: int = 100
    cleanup_interval: int = 60
    decay_enabled: bool = True

    def validate(self):
        assert self.window_seconds > 0, "window_seconds must be > 0"
        assert self.decay_half_life > 0, "decay_half_life must be > 0"
        assert self.max_events_per_user > 0, "max_events_per_user must be > 0"
        assert self.cleanup_interval > 0, "cleanup_interval must be > 0"

