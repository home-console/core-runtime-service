"""
Risk Policy — Weighted event contributions and decision thresholds.

Design:
- Event weights defined by security policy
- Exponential decay function (older events less impact)
- Risk thresholds map score to action
- Deterministic, no randomness
- Configurable for different security postures

Policy table:
Event               Base Weight   Justification
SECRET_READ         5            Normal operation
MFA_SUCCESS         -5           Trust restoration
MFA_FAILURE         10           Failed authentication attempt
MFA_BRUTE_FORCE     20           Multiple failures
ACCESS_DENIED       15           Unauthorized attempt
SECRET_READ_SPIKE   25           Rate limit violation
SECRET_READ_BURST   30           Reconnaissance pattern
ACCOUNT_FROZEN      50           Severe incident
ELEVATION_CREATED   2            Legitimate gate
ELEVATION_EXPIRED   0            Normal expiry

Thresholds:
Score < 30 → ALLOW
30–59 → REQUIRE_MFA
60–79 → TEMP_BLOCK
≥80 → FREEZE
"""

import math
from typing import Dict
from core.security.risk.models import EventType, RiskAction, RiskConfig


class RiskPolicy:
    """Risk scoring policy with weights and thresholds."""
    
    # Base event weights
    DEFAULT_WEIGHTS: Dict[EventType, float] = {
        # Secret access (low impact)
        EventType.SECRET_READ: 5.0,
        EventType.ELEVATION_CREATED: 2.0,
        EventType.ELEVATION_EXPIRED: 0.0,
        EventType.ACCESS_ALLOWED: 1.0,
        
        # MFA (medium impact)
        EventType.MFA_SUCCESS: -5.0,  # Negative = trust restoration
        EventType.MFA_FAILURE: 10.0,
        EventType.MFA_BRUTE_FORCE: 20.0,
        
        # Access violations (high impact)
        EventType.ACCESS_DENIED: 15.0,
        
        # Anomalies (very high impact)
        EventType.SECRET_READ_SPIKE: 25.0,
        EventType.SECRET_READ_BURST: 30.0,
        
        # Account issues (critical)
        EventType.ACCOUNT_FROZEN: 50.0,
        EventType.ACCOUNT_UNFROZEN: -20.0,
    }
    
    # Risk action thresholds
    THRESHOLDS = {
        30: RiskAction.REQUIRE_MFA,
        60: RiskAction.TEMP_BLOCK,
        80: RiskAction.FREEZE,
    }
    
    def __init__(self, weights: Dict[EventType, float] = None):
        """
        Initialize policy.
        
        Args:
            weights: Custom weights (uses defaults if None)
        """
        self.weights = weights or self.DEFAULT_WEIGHTS.copy()
    
    def get_weight(self, event_type: EventType) -> float:
        """
        Get weight for event type.
        
        Args:
            event_type: EventType
        
        Returns:
            Weight contribution
        """
        return self.weights.get(event_type, 0.0)
    
    def apply_decay(
        self,
        weight: float,
        age_seconds: float,
        half_life: int = 60,
    ) -> float:
        """
        Apply exponential decay to weight.
        
        Formula: weight_decayed = weight * 2^(-age / half_life)
        
        Interpretation:
        - age = 0s: Full weight
        - age = half_life: 50% of weight
        - age = 2*half_life: 25% of weight
        - age >> half_life: approaches 0
        
        Args:
            weight: Original weight
            age_seconds: Event age in seconds
            half_life: Half-life period in seconds
        
        Returns:
            Decayed weight
        """
        if age_seconds <= 0:
            return weight
        
        # Formula: 2^(-age / half_life) = e^(-age * ln(2) / half_life)
        decay_factor = math.exp(-age_seconds * math.log(2) / half_life)
        return weight * decay_factor
    
    def score_to_action(self, score: float) -> RiskAction:
        """
        Map risk score to action.
        
        Args:
            score: Risk score (0-100)
        
        Returns:
            RiskAction
        """
        if score < 30:
            return RiskAction.ALLOW
        elif score < 60:
            return RiskAction.REQUIRE_MFA
        elif score < 80:
            return RiskAction.TEMP_BLOCK
        else:
            return RiskAction.FREEZE
    
    def action_to_reason(self, action: RiskAction, score: float) -> str:
        """Generate human-readable reason for action."""
        if action == RiskAction.ALLOW:
            return f"Low risk (score: {score:.1f}/100); normal access allowed"
        elif action == RiskAction.REQUIRE_MFA:
            return f"Medium risk (score: {score:.1f}/100); additional MFA required"
        elif action == RiskAction.TEMP_BLOCK:
            return f"High risk (score: {score:.1f}/100); access temporarily blocked"
        else:
            return f"Critical risk (score: {score:.1f}/100); account frozen"
