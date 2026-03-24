"""
Trust State Models — Immutable data structures for trust tracking.

Core types:
- TrustLevel: User's current trust state
- TrustState: Snapshot of trust at a moment in time
- TrustDecision: Engine output (action + new state + reason)
- TrustAction: Recommended action

Design: Immutable, audit-friendly, deterministic
"""

from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, UTC
from typing import Any, Optional


class TrustLevel(str, Enum):
    """User's trust level."""
    
    NORMAL = "normal"                          # Normal: low risk
    ELEVATED_RISK = "elevated_risk"            # Elevated: medium risk
    COOLDOWN = "cooldown"                      # Cooldown: recovering
    TEMP_BLOCKED = "temp_blocked"              # Temporarily blocked
    FROZEN = "frozen"                          # Account frozen


class TrustAction(str, Enum):
    """Recommended trust action."""
    
    ALLOW = "allow"                            # Proceed normally
    REQUIRE_MFA = "require_mfa"                # Challenge user
    TEMP_BLOCK = "temp_block"                  # Block temporarily
    FREEZE = "freeze"                          # Freeze account
    RESTORE = "restore"                        # Restore trust (automatic)
    UNFREEZE = "unfreeze"                      # Unfreeze account


@dataclass(frozen=True)
class TrustState:
    """
    Immutable snapshot of user's trust state.
    
    Properties:
    - user_id: User identifier
    - level: Current TrustLevel (NORMAL/ELEVATED_RISK/COOLDOWN/TEMP_BLOCKED/FROZEN)
    - risk_score: Current risk score (0-100)
    - last_violation_at: When last security violation occurred
    - freeze_until: When freeze expires (if frozen)
    - cooldown_until: When cooldown expires (if in cooldown)
    - restored_at: When trust was last restored
    - metadata: Additional context (no secrets)
    
    Design:
    - Immutable: prevents accidental modification
    - Audit-friendly: contains no secrets
    - Deterministic: same inputs always produce same output
    
    Transitions:
    NORMAL → ELEVATED_RISK (risk rises)
    ELEVATED_RISK → NORMAL (risk falls below threshold)
    ELEVATED_RISK → COOLDOWN (after being blocked)
    COOLDOWN → NORMAL (cooldown expires)
    NORMAL/ELEVATED_RISK → TEMP_BLOCKED (temporary block)
    TEMP_BLOCKED → NORMAL/ELEVATED_RISK (block expires)
    ANY → FROZEN (critical incident)
    FROZEN → COOLDOWN (auto-unfreeze, if enabled)
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
        """Validate state consistency."""
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
    """
    Result of trust evaluation.
    
    Properties:
    - action: Recommended action (ALLOW/REQUIRE_MFA/TEMP_BLOCK/FREEZE/RESTORE/UNFREEZE)
    - new_state: Updated trust state
    - reason: Human-readable explanation
    - events: Trust events triggered by this decision
    - timestamp: When decision was made
    
    Design:
    - Deterministic: same inputs → same output
    - Audit-friendly: reasons documented
    - Event-emitting: triggers audit logging
    """
    
    action: TrustAction
    new_state: TrustState
    reason: str
    events: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    
    def __post_init__(self):
        """Validate decision consistency."""
        # Action must match state
        if self.action == TrustAction.FREEZE and self.new_state.level != TrustLevel.FROZEN:
            raise ValueError("FREEZE action requires FROZEN state")
        
        if self.action == TrustAction.TEMP_BLOCK and self.new_state.level != TrustLevel.TEMP_BLOCKED:
            raise ValueError("TEMP_BLOCK action requires TEMP_BLOCKED state")
        
        if self.action == TrustAction.RESTORE and self.new_state.level != TrustLevel.NORMAL:
            raise ValueError("RESTORE action requires NORMAL state")
        
        if self.action == TrustAction.UNFREEZE and self.new_state.level != TrustLevel.COOLDOWN:
            raise ValueError("UNFREEZE action requires COOLDOWN state")


@dataclass
class TrustConfig:
    """
    Configuration for trust engine.
    
    Properties:
    - risk_decay_half_life_seconds: How long until risk halves (default 60)
    - cooldown_period_seconds: Duration of cooldown after violation (default 600 = 10 min)
    - temp_block_duration_seconds: Duration of temporary block (default 300 = 5 min)
    - auto_unfreeze_enabled: Allow automatic unfreeze (default True)
    - freeze_duration_seconds: Duration of freeze before auto-unfreeze (default 3600 = 1 hour)
    - recovery_threshold: Risk score threshold for recovery (default 25.0)
    - restore_risk_score: Risk score to set on restore (default 5.0)
    - cleanup_interval_seconds: Cleanup task interval (default 60)
    """
    
    risk_decay_half_life_seconds: int = 60
    cooldown_period_seconds: int = 600           # 10 minutes
    temp_block_duration_seconds: int = 300       # 5 minutes
    auto_unfreeze_enabled: bool = True
    freeze_duration_seconds: int = 3600          # 1 hour
    recovery_threshold: float = 25.0
    restore_risk_score: float = 5.0
    cleanup_interval_seconds: int = 60
    
    def __post_init__(self):
        """Validate configuration."""
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


# Configuration Profiles

class TrustConfigs:
    """Pre-built configuration profiles."""
    
    STRICT = TrustConfig(
        risk_decay_half_life_seconds=120,      # Longer memory
        cooldown_period_seconds=1800,          # 30 minutes cooldown
        temp_block_duration_seconds=600,       # 10 minutes block
        freeze_duration_seconds=86400,         # 24 hours freeze
        auto_unfreeze_enabled=False,           # Manual unfreeze only
        recovery_threshold=10.0,               # Hard to recover
    )
    
    BALANCED = TrustConfig(
        risk_decay_half_life_seconds=60,       # Default
        cooldown_period_seconds=600,           # 10 minutes
        temp_block_duration_seconds=300,       # 5 minutes
        freeze_duration_seconds=3600,          # 1 hour
        auto_unfreeze_enabled=True,
        recovery_threshold=25.0,               # Default
    )
    
    PRODUCTION = TrustConfig(
        risk_decay_half_life_seconds=90,       # Moderate memory
        cooldown_period_seconds=900,           # 15 minutes
        temp_block_duration_seconds=300,       # 5 minutes
        freeze_duration_seconds=7200,          # 2 hours
        auto_unfreeze_enabled=True,
        recovery_threshold=30.0,               # Allow recovery
    )
    
    AGGRESSIVE = TrustConfig(
        risk_decay_half_life_seconds=30,       # Fast decay
        cooldown_period_seconds=300,           # 5 minutes cooldown
        temp_block_duration_seconds=120,       # 2 minutes block
        freeze_duration_seconds=1800,          # 30 minutes freeze
        auto_unfreeze_enabled=True,            # Quick recovery
        recovery_threshold=40.0,               # Easy to recover
    )
