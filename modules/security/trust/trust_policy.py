"""
Trust Policy — Decision logic and state transitions.

Defines:
- How trust levels transition based on risk scores
- Recovery thresholds and timings
- Escalation logic during cooldown
"""

from datetime import datetime, timedelta
from modules.security.trust.trust_state import (
    TrustLevel,
    TrustAction,
    TrustState,
    TrustConfig,
)


class TrustPolicy:
    """Decision policy for trust state transitions."""
    
    def __init__(self, config: TrustConfig):
        """
        Initialize trust policy.
        
        Args:
            config: TrustConfig with thresholds and durations
        """
        self.config = config
    
    def evaluate(
        self,
        current_state: TrustState,
        new_risk_score: float,
        current_time: datetime,
    ) -> tuple[TrustAction, TrustLevel]:
        """
        Evaluate trust and determine action.
        
        Logic:
        1. Check if FROZEN state has expired → UNFREEZE
        2. Check if COOLDOWN has expired → move to new level
        3. Check if TEMP_BLOCKED has expired → move to new level
        4. If in COOLDOWN and risk rises → ESCALATE
        5. Normal evaluation: risk → level mapping
        
        Args:
            current_state: Current trust state
            new_risk_score: Updated risk score (0-100)
            current_time: Current timestamp
        
        Returns:
            (TrustAction, new_level)
        """
        current_level = current_state.level
        
        # Step 1: Handle FROZEN expiration
        if current_level == TrustLevel.FROZEN:
            if current_state.freeze_until and current_time >= current_state.freeze_until:
                if self.config.auto_unfreeze_enabled:
                    return TrustAction.UNFREEZE, TrustLevel.COOLDOWN
            return TrustAction.FREEZE, TrustLevel.FROZEN
        
        # Step 2: Handle COOLDOWN expiration
        if current_level == TrustLevel.COOLDOWN:
            if current_state.cooldown_until and current_time >= current_state.cooldown_until:
                # Cooldown expired, evaluate new level
                new_level = self._risk_to_level(new_risk_score)
                action = TrustAction.RESTORE if new_level == TrustLevel.NORMAL else TrustAction.ALLOW
                return action, new_level
            else:
                # Still in cooldown
                # If risk rises, escalate
                if new_risk_score >= 70:
                    return TrustAction.TEMP_BLOCK, TrustLevel.TEMP_BLOCKED
                return TrustAction.ALLOW, TrustLevel.COOLDOWN
        
        # Step 3: Handle TEMP_BLOCKED expiration/escalation/recovery
        if current_level == TrustLevel.TEMP_BLOCKED:
            # Check if risk has escalated to FROZEN level
            if new_risk_score >= 80:
                return TrustAction.FREEZE, TrustLevel.FROZEN
            
            # Check time-based expiration
            if current_state.cooldown_until and current_time >= current_state.cooldown_until:
                # Block expired by time, evaluate new level
                new_level = self._risk_to_level(new_risk_score)
                action = TrustAction.RESTORE if new_level == TrustLevel.NORMAL else TrustAction.ALLOW
                return action, new_level
            else:
                # Still in block period, but check if risk has improved
                if new_risk_score < 70:  # Below TEMP_BLOCK threshold
                    # Risk has improved, allow recovery
                    new_level = self._risk_to_level(new_risk_score)
                    action = TrustAction.RESTORE if new_level == TrustLevel.NORMAL else TrustAction.ALLOW
                    return action, new_level
                else:
                    # Still blocked at this level
                    return TrustAction.TEMP_BLOCK, TrustLevel.TEMP_BLOCKED
        
        # Step 4: Normal evaluation (NORMAL or ELEVATED_RISK)
        # Check for critical risk → FREEZE
        if new_risk_score >= 80:
            return TrustAction.FREEZE, TrustLevel.FROZEN
        
        # Check for high risk → TEMP_BLOCK with cooldown
        if new_risk_score >= 70:
            return TrustAction.TEMP_BLOCK, TrustLevel.TEMP_BLOCKED
        
        # Check for medium risk → REQUIRE_MFA
        if new_risk_score >= self.config.recovery_threshold:
            return TrustAction.REQUIRE_MFA, TrustLevel.ELEVATED_RISK
        
        # Risk is low → NORMAL
        if current_level == TrustLevel.ELEVATED_RISK and new_risk_score < self.config.recovery_threshold:
            return TrustAction.RESTORE, TrustLevel.NORMAL
        
        # Default: ALLOW with current level
        action = TrustAction.ALLOW
        return action, current_level
    
    def _risk_to_level(self, risk_score: float) -> TrustLevel:
        """Map risk score to trust level."""
        if risk_score >= 80:
            return TrustLevel.FROZEN
        elif risk_score >= 70:
            return TrustLevel.TEMP_BLOCKED
        elif risk_score >= self.config.recovery_threshold:
            return TrustLevel.ELEVATED_RISK
        else:
            return TrustLevel.NORMAL
    
    def calculate_status_duration(self, action: TrustAction) -> int:
        """Get duration (seconds) for status transitions."""
        if action == TrustAction.FREEZE:
            return self.config.freeze_duration_seconds
        elif action == TrustAction.TEMP_BLOCK:
            return self.config.temp_block_duration_seconds
        elif action == TrustAction.REQUIRE_MFA:
            # No duration for require_mfa
            return 0
        elif action == TrustAction.ALLOW:
            # No duration for allow
            return 0
        return 0
    
    def get_next_state_transition(
        self,
        current_state: TrustState,
        action: TrustAction,
        new_level: TrustLevel,
        risk_score: float,
        current_time: datetime,
    ) -> TrustState:
        """
        Calculate next state based on action and new level.
        
        Args:
            current_state: Current trust state
            action: Action to apply
            new_level: Target trust level (from evaluate)
            risk_score: Current risk score
            current_time: Current timestamp
        
        Returns:
            New TrustState
        """
        now = current_time
        
        if action == TrustAction.FREEZE:
            freeze_until = now + timedelta(
                seconds=self.config.freeze_duration_seconds
            )
            return TrustState(
                user_id=current_state.user_id,
                level=TrustLevel.FROZEN,
                risk_score=risk_score,
                last_violation_at=now,
                freeze_until=freeze_until,
                metadata=current_state.metadata,
            )
        
        elif action == TrustAction.TEMP_BLOCK:
            cooldown_until = now + timedelta(
                seconds=self.config.temp_block_duration_seconds
            )
            return TrustState(
                user_id=current_state.user_id,
                level=TrustLevel.TEMP_BLOCKED,
                risk_score=risk_score,
                last_violation_at=now,
                cooldown_until=cooldown_until,
                metadata=current_state.metadata,
            )
        
        elif action == TrustAction.UNFREEZE:
            cooldown_until = now + timedelta(
                seconds=self.config.cooldown_period_seconds
            )
            return TrustState(
                user_id=current_state.user_id,
                level=TrustLevel.COOLDOWN,
                risk_score=self.config.restore_risk_score,
                last_violation_at=current_state.last_violation_at,
                cooldown_until=cooldown_until,
                restored_at=now,
                metadata=current_state.metadata,
            )
        
        elif action == TrustAction.RESTORE:
            return TrustState(
                user_id=current_state.user_id,
                level=TrustLevel.NORMAL,
                risk_score=self.config.restore_risk_score,
                last_violation_at=current_state.last_violation_at,
                restored_at=now,
                metadata=current_state.metadata,
            )
        
        elif action == TrustAction.REQUIRE_MFA:
            return TrustState(
                user_id=current_state.user_id,
                level=TrustLevel.ELEVATED_RISK,
                risk_score=risk_score,
                last_violation_at=current_state.last_violation_at,
                metadata=current_state.metadata,
            )
        
        else:  # ALLOW - use the new_level from evaluate()
            # Handle state transitions from ALLOW
            if new_level == TrustLevel.NORMAL:
                return TrustState(
                    user_id=current_state.user_id,
                    level=TrustLevel.NORMAL,
                    risk_score=risk_score,
                    last_violation_at=current_state.last_violation_at,
                    restored_at=now if current_state.level != TrustLevel.NORMAL else current_state.restored_at,
                    metadata=current_state.metadata,
                )
            elif new_level == TrustLevel.ELEVATED_RISK:
                return TrustState(
                    user_id=current_state.user_id,
                    level=TrustLevel.ELEVATED_RISK,
                    risk_score=risk_score,
                    last_violation_at=current_state.last_violation_at,
                    metadata=current_state.metadata,
                )
            elif new_level == TrustLevel.COOLDOWN:
                # Keep existing cooldown_until if transitioning within cooldown
                cooldown_until = current_state.cooldown_until or now + timedelta(
                    seconds=self.config.cooldown_period_seconds
                )
                return TrustState(
                    user_id=current_state.user_id,
                    level=TrustLevel.COOLDOWN,
                    risk_score=risk_score,
                    last_violation_at=current_state.last_violation_at,
                    cooldown_until=cooldown_until,
                    restored_at=current_state.restored_at,
                    metadata=current_state.metadata,
                )
            else:
                # Default: keep current level (shouldn't reach here)
                return TrustState(
                    user_id=current_state.user_id,
                    level=current_state.level,
                    risk_score=risk_score,
                    last_violation_at=current_state.last_violation_at,
                    restored_at=current_state.restored_at,
                    freeze_until=current_state.freeze_until,
                    cooldown_until=current_state.cooldown_until,
                    metadata=current_state.metadata,
                )
    
    def action_to_reason(self, action: TrustAction, risk_score: float) -> str:
        """Get human-readable reason for action."""
        reasons = {
            TrustAction.ALLOW: f"Low risk (score {risk_score:.1f}/100); access allowed",
            TrustAction.REQUIRE_MFA: f"Medium risk (score {risk_score:.1f}/100); verify identity",
            TrustAction.TEMP_BLOCK: f"High risk (score {risk_score:.1f}/100); temporarily blocked",
            TrustAction.FREEZE: f"Critical risk (score {risk_score:.1f}/100); account frozen",
            TrustAction.RESTORE: f"Risk resolved; trust restored",
            TrustAction.UNFREEZE: f"Freeze period expired; entering cooldown",
        }
        return reasons.get(action, "Unknown action")
