"""
Risk Engine — Core adaptive risk scoring and decision-making.

Flow:
1. Record event → stored in memory
2. Assess user → load recent events, calculate score, determine action
3. Cleanup → remove expired events

Design:
- Stateless decisions (same input → same output)
- Stateful memory (persists across assessments)
- Deterministic scoring with decay
- Integration with audit trail
"""

from typing import Optional, TYPE_CHECKING
import time

from core.security.risk.models import (
    RiskEvent,
    RiskAssessment,
    RiskAction,
    EventType,
    RiskConfig,
)
from core.security.risk.memory import RiskMemory
from core.security.risk.policy import RiskPolicy

if TYPE_CHECKING:
    from core.audit.binder import AuditBinder


class RiskEngine:
    """Adaptive risk scoring engine."""
    
    def __init__(
        self,
        memory: Optional[RiskMemory] = None,
        policy: Optional[RiskPolicy] = None,
        config: Optional[RiskConfig] = None,
        audit_binder: Optional["AuditBinder"] = None,
    ):
        """
        Initialize risk engine.
        
        Args:
            memory: RiskMemory instance (creates if None)
            policy: RiskPolicy instance (creates if None)
            config: RiskConfig (uses defaults if None)
            audit_binder: Optional AuditBinder for logging
        """
        self.config = config or RiskConfig()
        self.memory = memory or RiskMemory(self.config)
        self.policy = policy or RiskPolicy()
        self.audit_binder = audit_binder
    
    async def start(self) -> None:
        """Start background cleanup task."""
        await self.memory.start_cleanup()
    
    async def stop(self) -> None:
        """Stop background cleanup task."""
        await self.memory.stop_cleanup()
    
    async def record_event(
        self,
        event: RiskEvent,
        log_to_audit: bool = False,
    ) -> None:
        """
        Record a risk event.
        
        This is called when significant events occur:
        - MFA success/failure
        - Secret access patterns
        - Access denials
        - Account actions
        
        Args:
            event: RiskEvent to record
            log_to_audit: Whether to log to audit trail
        """
        # Store in memory
        await self.memory.record(event)
        
        # Optionally log to audit
        if log_to_audit and self.audit_binder:
            try:
                from core.audit.events import credential_risk_event
                audit_event = credential_risk_event(
                    user_id=event.user_id,
                    event_type=event.event_type.value,
                    risk_weight=event.weight,
                    **event.metadata,
                )
                await self.audit_binder.append(audit_event)
            except Exception as e:
                print(f"[WARNING] Failed to audit risk event: {e}")
    
    async def assess(
        self,
        user_id: str,
        current_time: Optional[float] = None,
    ) -> RiskAssessment:
        """
        Assess current risk for user.
        
        Flow:
        1. Load recent events from memory
        2. Calculate weighted sum
        3. Apply decay to older events
        4. Clamp to [0, 100]
        5. Determine action based on thresholds
        6. Return assessment
        
        Args:
            user_id: User identifier
            current_time: Current timestamp (uses now() if None)
        
        Returns:
            RiskAssessment with score, action, and reasoning
        """
        if current_time is None:
            current_time = time.time()
        
        # Load recent events
        events = await self.memory.get_recent(user_id, current_time)
        
        # Calculate weighted score
        score = 0.0
        reasons = []
        
        # Group by event type for explanation
        event_contributions = {}
        
        for event in events:
            # Use event's weight directly (already computed)
            weight = event.weight
            
            # Apply decay if enabled
            if self.config.decay_enabled:
                age = event.age_seconds(current_time)
                weight = self.policy.apply_decay(
                    weight,
                    age,
                    self.config.decay_half_life,
                )
            
            # Add to score
            score += weight
            
            # Track for explanation
            event_type_str = event.event_type.value
            if event_type_str not in event_contributions:
                event_contributions[event_type_str] = 0.0
            event_contributions[event_type_str] += weight
        
        # Clamp score to [0, 100]
        score = max(0.0, min(100.0, score))
        
        # Determine action
        action = self.policy.score_to_action(score)
        
        # Build reasons
        reasons.append(self.policy.action_to_reason(action, score))
        
        # Add top contributing factors
        if event_contributions:
            sorted_contrib = sorted(
                event_contributions.items(),
                key=lambda x: abs(x[1]),
                reverse=True,
            )
            for event_type, contrib_score in sorted_contrib[:3]:
                if contrib_score != 0:
                    sign = "+" if contrib_score > 0 else ""
                    reasons.append(f"{event_type}: {sign}{contrib_score:.1f}")
        
        return RiskAssessment(
            score=score,
            action=action,
            reasons=reasons,
            events_considered=len(events),
        )
    
    async def get_user_score(
        self,
        user_id: str,
        current_time: Optional[float] = None,
    ) -> float:
        """Get current risk score for user."""
        assessment = await self.assess(user_id, current_time)
        return assessment.score
    
    async def get_user_action(
        self,
        user_id: str,
        current_time: Optional[float] = None,
    ) -> RiskAction:
        """Get current risk action for user."""
        assessment = await self.assess(user_id, current_time)
        return assessment.action
    
    async def reset_user_risk(self, user_id: str) -> None:
        """
        Reset all risk events for user.
        
        Used when account is unfrozen or trust is restored.
        """
        await self.memory.clear_user(user_id)
    
    async def stats(self) -> dict:
        """Get engine statistics."""
        memory_stats = await self.memory.stats()
        return {
            "engine": "risk_engine_v1",
            "policy": "weighted_decay",
            **memory_stats,
        }
