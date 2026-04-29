"""
Shared domain: trust models.

Важно: этот модуль не должен импортировать ничего из modules.security или modules.credentials.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Optional


class TrustLevel(str, Enum):
    """User's trust level."""

    NORMAL = "normal"  # Normal: low risk
    ELEVATED_RISK = "elevated_risk"  # Elevated: medium risk
    COOLDOWN = "cooldown"  # Cooldown: recovering
    TEMP_BLOCKED = "temp_blocked"  # Temporarily blocked
    FROZEN = "frozen"  # Account frozen


class TrustAction(str, Enum):
    """Recommended trust action."""

    ALLOW = "allow"  # Proceed normally
    REQUIRE_MFA = "require_mfa"  # Challenge user
    TEMP_BLOCK = "temp_block"  # Block temporarily
    FREEZE = "freeze"  # Freeze account
    RESTORE = "restore"  # Restore trust (automatic)
    UNFREEZE = "unfreeze"  # Unfreeze account


@dataclass(frozen=True)
class TrustState:
    """
    Immutable snapshot of user's trust state.
    """

    user_id: str
    level: TrustLevel
    risk_score: float
    last_violation_at: Optional[datetime] = None
    freeze_until: Optional[datetime] = None
    cooldown_until: Optional[datetime] = None
    restored_at: Optional[datetime] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # Risk score bounds
        if not 0 <= self.risk_score <= 100:
            raise ValueError(f"risk_score must be [0, 100], got {self.risk_score}")

        # If frozen, must have freeze_until
        if self.level == TrustLevel.FROZEN and self.freeze_until is None:
            raise ValueError("FROZEN state requires freeze_until")

        # If in cooldown, must have cooldown_until
        if self.level == TrustLevel.COOLDOWN and self.cooldown_until is None:
            raise ValueError("COOLDOWN state requires cooldown_until")


@dataclass(frozen=True)
class TrustDecision:
    """Result of trust evaluation."""

    action: TrustAction
    new_state: TrustState
    reason: str
    events: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def __post_init__(self):
        # Action must match state
        if self.action == TrustAction.FREEZE and self.new_state.level != TrustLevel.FROZEN:
            raise ValueError("FREEZE action requires FROZEN state")

        if (
            self.action == TrustAction.TEMP_BLOCK
            and self.new_state.level != TrustLevel.TEMP_BLOCKED
        ):
            raise ValueError("TEMP_BLOCK action requires TEMP_BLOCKED state")

        if self.action == TrustAction.RESTORE and self.new_state.level != TrustLevel.NORMAL:
            raise ValueError("RESTORE action requires NORMAL state")

        if (
            self.action == TrustAction.UNFREEZE
            and self.new_state.level != TrustLevel.COOLDOWN
        ):
            raise ValueError("UNFREEZE action requires COOLDOWN state")


@dataclass
class TrustConfig:
    """Configuration for trust engine."""

    risk_decay_half_life_seconds: int = 60
    cooldown_period_seconds: int = 600  # 10 minutes
    temp_block_duration_seconds: int = 300  # 5 minutes
    auto_unfreeze_enabled: bool = True
    freeze_duration_seconds: int = 3600  # 1 hour
    recovery_threshold: float = 25.0
    restore_risk_score: float = 5.0
    cleanup_interval_seconds: int = 60

    def __post_init__(self):
        if self.risk_decay_half_life_seconds <= 0:
            raise ValueError("risk_decay_half_life_seconds must be positive")
        if self.cooldown_period_seconds <= 0:
            raise ValueError("cooldown_period_seconds must be positive")
        if self.temp_block_duration_seconds <= 0:
            raise ValueError("temp_block_duration_seconds must be positive")
        if self.freeze_duration_seconds <= 0:
            raise ValueError("freeze_duration_seconds must be positive")
        if not 0 <= self.recovery_threshold <= 100:
            raise ValueError("recovery_threshold must be [0, 100]")
        if not 0 <= self.restore_risk_score <= 100:
            raise ValueError("restore_risk_score must be [0, 100]")
        if self.cleanup_interval_seconds <= 0:
            raise ValueError("cleanup_interval_seconds must be positive")


class TrustConfigs:
    """Pre-built configuration profiles."""

    STRICT = TrustConfig(
        risk_decay_half_life_seconds=120,  # Longer memory
        cooldown_period_seconds=1800,  # 30 minutes cooldown
        temp_block_duration_seconds=600,  # 10 minutes block
        freeze_duration_seconds=86400,  # 24 hours freeze
        auto_unfreeze_enabled=False,  # Manual unfreeze only
        recovery_threshold=10.0,  # Hard to recover
    )

    BALANCED = TrustConfig(
        risk_decay_half_life_seconds=60,  # Default
        cooldown_period_seconds=600,  # 10 minutes
        temp_block_duration_seconds=300,  # 5 minutes
        freeze_duration_seconds=3600,  # 1 hour
        auto_unfreeze_enabled=True,
        recovery_threshold=25.0,  # Default
    )

    PRODUCTION = TrustConfig(
        risk_decay_half_life_seconds=90,  # Moderate memory
        cooldown_period_seconds=900,  # 15 minutes
        temp_block_duration_seconds=300,  # 5 minutes
        freeze_duration_seconds=7200,  # 2 hours
        auto_unfreeze_enabled=True,
        recovery_threshold=30.0,  # Allow recovery
    )

    AGGRESSIVE = TrustConfig(
        risk_decay_half_life_seconds=30,  # Fast decay
        cooldown_period_seconds=300,  # 5 minutes cooldown
        temp_block_duration_seconds=120,  # 2 minutes block
        freeze_duration_seconds=1800,  # 30 minutes freeze
        auto_unfreeze_enabled=True,  # Quick recovery
        recovery_threshold=40.0,  # Easy to recover
    )

