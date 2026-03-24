"""
Trust Engine — Core trust evaluation and state management.

Manages user trust states and makes decisions based on risk scores.
Handles automatic recovery, cooldowns, and state transitions.

Design:
- In-memory state storage (per-user)
- Stateless decision logic (same input → same output)
- Time-based transitions (cleanup task)
- Deterministic (no randomness)
"""

from datetime import datetime, timedelta, UTC
from typing import Optional, TYPE_CHECKING
import asyncio
import time

from modules.security.trust.trust_state import (
    TrustState,
    TrustLevel,
    TrustAction,
    TrustDecision,
    TrustConfig,
    TrustConfigs,
)
from modules.security.trust.trust_policy import TrustPolicy

if TYPE_CHECKING:
    from core.audit.binder import AuditBinder


class TrustEngine:
    """Trust evaluation and state management engine."""
    
    def __init__(
        self,
        config: Optional[TrustConfig] = None,
        audit_binder: Optional["AuditBinder"] = None,
    ):
        """
        Initialize trust engine.
        
        Args:
            config: TrustConfig (uses BALANCED if None)
            audit_binder: Optional AuditBinder for logging
        """
        self.config = config or TrustConfigs.BALANCED
        self.policy = TrustPolicy(self.config)
        self.audit_binder = audit_binder
        
        # In-memory state: user_id → TrustState
        self._states: dict[str, TrustState] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None
    
    def start(self) -> None:
        """Start background cleanup task."""
        if self._cleanup_task is None or self._cleanup_task.done():
            try:
                loop = asyncio.get_running_loop()
                self._cleanup_task = loop.create_task(self._cleanup_loop())
            except RuntimeError:
                # No running loop, create new one
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self._cleanup_task = loop.create_task(self._cleanup_loop())
    
    def stop(self) -> None:
        """Stop background cleanup task."""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
    
    async def get_state(self, user_id: str) -> TrustState:
        """
        Get current trust state for user.
        
        Returns default NORMAL state if not found.
        """
        async with self._lock:
            if user_id not in self._states:
                return TrustState(
                    user_id=user_id,
                    level=TrustLevel.NORMAL,
                    risk_score=0.0,
                )
            return self._states[user_id]
    
    async def evaluate(
        self,
        user_id: str,
        risk_score: float,
        current_time: Optional[float] = None,
    ) -> TrustDecision:
        """
        Evaluate trust and make decision.
        
        Flow:
        1. Load current state
        2. Apply policy logic
        3. Calculate new state
        4. Check for state changes (trigger events)
        5. Store new state
        6. Return decision with events
        
        Args:
            user_id: User identifier
            risk_score: Current risk score (0-100)
            current_time: Current timestamp (uses now() if None)
        
        Returns:
            TrustDecision with action and new state
        """
        if current_time is None:
            current_time = time.time()
        
        current_dt = datetime.fromtimestamp(current_time, tz=UTC)
        
        # Get current state
        current_state = await self.get_state(user_id)
        
        # Evaluate action
        action, new_level = self.policy.evaluate(
            current_state,
            risk_score,
            current_dt,
        )
        
        # Calculate next state
        new_state = self.policy.get_next_state_transition(
            current_state,
            action,
            new_level,
            risk_score,
            current_dt,
        )
        
        # Track state changes for audit
        events = []
        if current_state.level != new_state.level:
            events.append(f"TRUST_STATE_CHANGED:{current_state.level.value}→{new_state.level.value}")
        
        if action == TrustAction.RESTORE:
            events.append("TRUST_RESTORED")
        elif action == TrustAction.UNFREEZE:
            events.append("TRUST_UNFROZEN")
        elif action == TrustAction.FREEZE:
            events.append("TRUST_FROZEN")
        elif action == TrustAction.TEMP_BLOCK:
            events.append("TRUST_TEMP_BLOCKED")
        
        # Store new state
        async with self._lock:
            self._states[user_id] = new_state
        
        # Audit logging
        if self.audit_binder and events:
            try:
                from core.audit.events import trust_state_changed_event
                for event_name in events:
                    audit_event = trust_state_changed_event(
                        user_id=user_id,
                        event=event_name,
                        risk_score=risk_score,
                        new_level=new_state.level.value,
                    )
                    await self.audit_binder.append(audit_event)
            except Exception as e:
                print(f"[WARNING] Failed to audit trust event: {e}")
        
        return TrustDecision(
            action=action,
            new_state=new_state,
            reason=self.policy.action_to_reason(action, risk_score),
            events=events,
            timestamp=current_dt.isoformat(),
        )
    
    async def force_state(
        self,
        user_id: str,
        level: TrustLevel,
        risk_score: float = 0.0,
        reason: str = "Manual override",
    ) -> TrustState:
        """
        Manually set trust state (for admin override).
        
        Args:
            user_id: User identifier
            level: Target trust level
            risk_score: Risk score to set
            reason: Reason for override
        
        Returns:
            New TrustState
        """
        current_time = datetime.now(UTC)
        
        # Set appropriate timestamps based on level
        freeze_until = None
        cooldown_until = None
        
        if level == TrustLevel.FROZEN:
            freeze_until = current_time + timedelta(seconds=self.config.freeze_duration_seconds)
        elif level == TrustLevel.COOLDOWN:
            # Manual override to COOLDOWN is used as a fast recovery state in tests/admin flows.
            # Mark cooldown as already elapsed so the next low-risk evaluate() can restore to NORMAL.
            cooldown_until = current_time
        elif level == TrustLevel.TEMP_BLOCKED:
            cooldown_until = current_time + timedelta(seconds=self.config.temp_block_duration_seconds)
        
        new_state = TrustState(
            user_id=user_id,
            level=level,
            risk_score=risk_score,
            freeze_until=freeze_until,
            cooldown_until=cooldown_until,
            metadata={"reason": reason, "manual_override": True},
        )
        
        async with self._lock:
            self._states[user_id] = new_state
        
        # Audit override
        if self.audit_binder:
            try:
                from core.audit.events import trust_state_changed_event
                audit_event = trust_state_changed_event(
                    user_id=user_id,
                    event=f"TRUST_MANUAL_OVERRIDE:{level.value}",
                    risk_score=risk_score,
                    new_level=level.value,
                )
                await self.audit_binder.append(audit_event)
            except Exception as e:
                print(f"[WARNING] Failed to audit trust override: {e}")
        
        return new_state
    
    async def reset_user_trust(self, user_id: str) -> None:
        """
        Reset user's trust to NORMAL (for unfreeze or account reset).
        """
        async with self._lock:
            if user_id in self._states:
                del self._states[user_id]
    
    async def stats(self) -> dict:
        """Get engine statistics."""
        async with self._lock:
            states = self._states
        
        # Count by trust level
        level_counts = {}
        for state in states.values():
            level_counts[state.level.value] = level_counts.get(state.level.value, 0) + 1
        
        return {
            "engine": "trust_engine_v1",
            "total_users": len(states),
            "by_level": level_counts,
            "config": {
                "recovery_threshold": self.config.recovery_threshold,
                "cooldown_period_seconds": self.config.cooldown_period_seconds,
                "freeze_duration_seconds": self.config.freeze_duration_seconds,
                "auto_unfreeze_enabled": self.config.auto_unfreeze_enabled,
            },
        }
    
    async def _cleanup_loop(self) -> None:
        """Background cleanup task."""
        try:
            while True:
                await asyncio.sleep(self.config.cleanup_interval_seconds)
                await self._cleanup_expired_states()
        except asyncio.CancelledError:
            pass
    
    async def _cleanup_expired_states(self) -> None:
        """Remove expired states or reset them."""
        now = datetime.now(UTC)
        async with self._lock:
            to_remove = []
            for user_id, state in self._states.items():
                # Clean up expired frozen states
                if state.level == TrustLevel.FROZEN:
                    if state.freeze_until and now >= state.freeze_until:
                        if self.config.auto_unfreeze_enabled:
                            # Auto-unfreeze to cooldown
                            cooldown_until = now.timestamp() + self.config.cooldown_period_seconds
                            self._states[user_id] = TrustState(
                                user_id=user_id,
                                level=TrustLevel.COOLDOWN,
                                risk_score=self.config.restore_risk_score,
                                cooldown_until=datetime.fromtimestamp(cooldown_until, tz=UTC),
                            )
                
                # Clean up expired temp blocks
                elif state.level == TrustLevel.TEMP_BLOCKED:
                    if state.cooldown_until and now >= state.cooldown_until:
                        # Unblock to normal
                        self._states[user_id] = TrustState(
                            user_id=user_id,
                            level=TrustLevel.NORMAL,
                            risk_score=self.config.restore_risk_score,
                        )
                
                # Clean up expired cooldowns
                elif state.level == TrustLevel.COOLDOWN:
                    if state.cooldown_until and now >= state.cooldown_until:
                        # Restore to normal
                        self._states[user_id] = TrustState(
                            user_id=user_id,
                            level=TrustLevel.NORMAL,
                            risk_score=self.config.restore_risk_score,
                            restored_at=now,
                        )
