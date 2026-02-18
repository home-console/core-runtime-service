"""
Credential Rotation Policy Model

Defines rotation strategy, schedule, and configuration.
Part of credential lifecycle management system.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional
from datetime import datetime, timezone, timedelta


class RotationStrategy(str, Enum):
    """Strategy for rotating credentials."""
    
    MANUAL = "manual"                    # Only manual rotation via API
    GENERATE_NEW_SECRET = "generate_new"  # Auto-generate new secret
    AGENT_PUSH = "agent_push"           # Agent updates service with new secret
    CALLBACK_WEBHOOK = "callback_webhook"  # Call webhook to notify service


class RotationStatus(str, Enum):
    """Current rotation status of a credential."""
    
    IDLE = "idle"                       # No rotation in progress
    SCHEDULED = "scheduled"             # Rotation scheduled for future
    IN_PROGRESS = "in_progress"         # Rotation currently executing
    COMPLETED = "completed"             # Rotation just completed
    FAILED = "failed"                   # Rotation failed
    ROLLING_BACK = "rolling_back"       # Rolling back failed rotation
    ROLLED_BACK = "rolled_back"         # Rollback completed


@dataclass(frozen=True)
class RotationPolicy:
    """
    Immutable rotation policy for a credential.
    
    Defines when and how to rotate, grace periods, and strategy.
    
    Attributes:
        interval_seconds: Seconds between rotations (86400 = 1 day)
        auto_rotate: If True, automatic rotation is enabled
        grace_period_seconds: Time before rotation starts to warn/prepare
        strategy: How to perform rotation (manual, generate new, etc.)
        max_failures: Max consecutive failures before freezing account
        enable_notifications: If True, send notifications about rotation
    """
    
    interval_seconds: int
    auto_rotate: bool
    grace_period_seconds: int
    strategy: RotationStrategy
    max_failures: int = 3
    enable_notifications: bool = True
    
    def validate(self) -> None:
        """Validate policy fields."""
        if self.interval_seconds <= 0:
            raise ValueError("interval_seconds must be > 0")
        if self.grace_period_seconds < 0:
            raise ValueError("grace_period_seconds must be >= 0")
        if self.grace_period_seconds >= self.interval_seconds:
            raise ValueError("grace_period_seconds must be < interval_seconds")
        if self.max_failures <= 0:
            raise ValueError("max_failures must be > 0")
    
    @classmethod
    def daily(cls) -> "RotationPolicy":
        """Daily rotation policy with 1-hour grace period."""
        return cls(
            interval_seconds=86400,  # 1 day
            auto_rotate=True,
            grace_period_seconds=3600,  # 1 hour before
            strategy=RotationStrategy.GENERATE_NEW_SECRET,
            max_failures=3,
            enable_notifications=True
        )
    
    @classmethod
    def weekly(cls) -> "RotationPolicy":
        """Weekly rotation policy with 6-hour grace period."""
        return cls(
            interval_seconds=604800,  # 7 days
            auto_rotate=True,
            grace_period_seconds=21600,  # 6 hours before
            strategy=RotationStrategy.GENERATE_NEW_SECRET,
            max_failures=3,
            enable_notifications=True
        )
    
    @classmethod
    def manual_only(cls) -> "RotationPolicy":
        """Manual rotation only (no automatic)."""
        return cls(
            interval_seconds=86400,  # Still track interval
            auto_rotate=False,
            grace_period_seconds=0,
            strategy=RotationStrategy.MANUAL,
            max_failures=3,
            enable_notifications=False
        )
    
    def next_rotation_due(self, last_rotated_at: Optional[str]) -> str:
        """
        Calculate when next rotation is due.
        
        Args:
            last_rotated_at: ISO8601 UTC timestamp of last rotation
        
        Returns:
            ISO8601 UTC timestamp when next rotation is due
        """
        if last_rotated_at is None:
            # If never rotated, due immediately
            return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        
        # Parse last rotation time
        last_rotated = datetime.fromisoformat(
            last_rotated_at.replace("Z", "+00:00")
        )
        
        # Add interval to get next due time
        next_due = last_rotated + timedelta(seconds=self.interval_seconds)
        
        return next_due.isoformat().replace("+00:00", "Z")
    
    def grace_period_start(self, next_rotation_at: str) -> str:
        """
        Calculate when grace period starts (before rotation).
        
        Args:
            next_rotation_at: ISO8601 UTC timestamp when rotation is due
        
        Returns:
            ISO8601 UTC timestamp when grace period starts
        """
        rotation_time = datetime.fromisoformat(
            next_rotation_at.replace("Z", "+00:00")
        )
        
        # Grace period starts X seconds before rotation
        grace_start = rotation_time - timedelta(seconds=self.grace_period_seconds)
        
        return grace_start.isoformat().replace("+00:00", "Z")
    
    def is_in_grace_period(self, now: Optional[str] = None) -> bool:
        """
        Check if currently in grace period before rotation.
        
        Grace period is between: (next_rotation - grace_period) and next_rotation
        
        Args:
            now: Current time (ISO8601, default: now)
        
        Returns:
            True if currently in grace period
        """
        if now is None:
            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        
        current = datetime.fromisoformat(now.replace("Z", "+00:00"))
        
        # Grace period is always before rotation time
        # Implementation would compare with next_rotation_at
        # This is computed by RotationScheduler
        return False  # Placeholder
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "interval_seconds": self.interval_seconds,
            "auto_rotate": self.auto_rotate,
            "grace_period_seconds": self.grace_period_seconds,
            "strategy": self.strategy.value,
            "max_failures": self.max_failures,
            "enable_notifications": self.enable_notifications,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "RotationPolicy":
        """Create from dictionary."""
        policy = cls(
            interval_seconds=data["interval_seconds"],
            auto_rotate=data["auto_rotate"],
            grace_period_seconds=data["grace_period_seconds"],
            strategy=RotationStrategy(data["strategy"]),
            max_failures=data.get("max_failures", 3),
            enable_notifications=data.get("enable_notifications", True),
        )
        policy.validate()
        return policy


@dataclass(frozen=True)
class RotationState:
    """
    Immutable rotation state for a credential at a point in time.
    
    Tracks:
    - Last rotation timestamp
    - Next rotation timestamp
    - Current rotation status
    - Number of consecutive failures
    """
    
    last_rotated_at: Optional[str]  # ISO8601 UTC
    next_rotation_at: Optional[str]  # ISO8601 UTC
    rotation_status: RotationStatus
    failure_count: int = 0
    last_failure_reason: Optional[str] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "last_rotated_at": self.last_rotated_at,
            "next_rotation_at": self.next_rotation_at,
            "rotation_status": self.rotation_status.value,
            "failure_count": self.failure_count,
            "last_failure_reason": self.last_failure_reason,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "RotationState":
        """Create from dictionary."""
        return cls(
            last_rotated_at=data.get("last_rotated_at"),
            next_rotation_at=data.get("next_rotation_at"),
            rotation_status=RotationStatus(data["rotation_status"]),
            failure_count=data.get("failure_count", 0),
            last_failure_reason=data.get("last_failure_reason"),
        )
    
    @classmethod
    def new(cls) -> "RotationState":
        """Create new rotation state (never rotated)."""
        return cls(
            last_rotated_at=None,
            next_rotation_at=None,
            rotation_status=RotationStatus.IDLE,
            failure_count=0,
            last_failure_reason=None,
        )
