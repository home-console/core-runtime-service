"""
Risk Scoring Models — Data structures for adaptive risk assessment.

Core types:
- RiskAction: Decision the engine makes (ALLOW, REQUIRE_MFA, TEMP_BLOCK, FREEZE)
- RiskEvent: Single event contributing to risk
- RiskAssessment: Engine output (score + action + reasoning)

Design: Immutable, audit-friendly, no secrets stored.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from datetime import datetime, UTC


class RiskAction(str, Enum):
    """Risk-based decision action."""
    ALLOW = "allow"
    REQUIRE_MFA = "require_mfa"
    TEMP_BLOCK = "temporary_block"
    FREEZE = "freeze"


class EventType(str, Enum):
    """Event types contributing to risk score."""
    
    # Secret access
    SECRET_READ = "secret_read"
    SECRET_READ_SPIKE = "secret_read_spike"
    SECRET_READ_BURST = "secret_read_burst"
    
    # MFA
    MFA_SUCCESS = "mfa_success"
    MFA_FAILURE = "mfa_failure"
    MFA_BRUTE_FORCE = "mfa_brute_force"
    
    # RBAC
    ACCESS_ALLOWED = "access_allowed"
    ACCESS_DENIED = "access_denied"
    
    # Account
    ACCOUNT_FROZEN = "account_frozen"
    ACCOUNT_UNFROZEN = "account_unfrozen"
    
    # System
    ELEVATION_CREATED = "elevation_created"
    ELEVATION_EXPIRED = "elevation_expired"


@dataclass(frozen=True)
class RiskEvent:
    """
    Immutable event contributing to user's risk score.
    
    Properties:
    - user_id: User this event applies to
    - event_type: Type of event (from EventType enum)
    - weight: Contribution to risk score (-100 to +100)
    - timestamp: When event occurred (seconds since epoch)
    - metadata: Event context (no secrets)
    
    Design:
    - Positive weight = increases risk
    - Negative weight = decreases risk (trust restoration)
    - weight=0 = no contribution (informational)
    
    Examples:
    - SECRET_READ (normal): weight=5
    - MFA_FAILURE: weight=10
    - MFA_SUCCESS: weight=-5 (trust restoration)
    - SECRET_READ_SPIKE: weight=25
    """
    
    user_id: str
    event_type: EventType
    weight: float
    timestamp: float
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Validate weight range."""
        if not -100 <= self.weight <= 100:
            raise ValueError(f"weight must be in [-100, 100], got {self.weight}")
    
    def age_seconds(self, current_time: float) -> float:
        """How old is this event (in seconds)."""
        return max(0, current_time - self.timestamp)


@dataclass(frozen=True)
class RiskAssessment:
    """
    Result of risk assessment.
    
    Properties:
    - score: Risk score (0-100)
    - action: Recommended action
    - reasons: Human-readable explanation
    - events_considered: Number of events included
    
    Design:
    - Deterministic (same input → same output)
    - Audit-friendly (reasons logged)
    - No secrets in reasons
    
    Score interpretation:
    0–29: Low risk → ALLOW
    30–59: Medium risk → REQUIRE_MFA
    60–79: High risk → TEMP_BLOCK
    80+: Critical risk → FREEZE
    """
    
    score: float
    action: RiskAction
    reasons: list[str] = field(default_factory=list)
    events_considered: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    
    def __post_init__(self):
        """Validate score range."""
        if not 0 <= self.score <= 100:
            raise ValueError(f"score must be in [0, 100], got {self.score}")


@dataclass
class RiskConfig:
    """
    Configuration for risk engine.
    
    Parameters:
    - window_seconds: How long to keep events (default 300s = 5 min)
    - decay_half_life: Exponential decay half-life in seconds
    - max_events_per_user: Ring buffer size (default 100)
    - cleanup_interval: Background task interval (default 60s)
    - decay_enabled: Whether to apply exponential decay (default True)
    
    Design: Reasonable defaults for normal operations.
    """
    
    window_seconds: int = 300  # 5 minutes observation window
    decay_half_life: int = 60  # Events decay over 60 seconds
    max_events_per_user: int = 100
    cleanup_interval: int = 60
    decay_enabled: bool = True
    
    def validate(self):
        """Validate configuration."""
        assert self.window_seconds > 0, "window_seconds must be > 0"
        assert self.decay_half_life > 0, "decay_half_life must be > 0"
        assert self.max_events_per_user > 0, "max_events_per_user must be > 0"
        assert self.cleanup_interval > 0, "cleanup_interval must be > 0"
