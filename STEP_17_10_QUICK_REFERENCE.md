# Step 17.10 Quick Reference: Security Orchestrator

## Quick Start

### Basic Usage Pattern

```python
from modules.credentials.security_orchestrator import (
    CredentialSecurityOrchestrator,
    SecurityDecision,
    SecurityDecisionReason
)

# Initialize orchestrator with all 5 security components
orchestrator = CredentialSecurityOrchestrator(
    rbac_enforcer=rbac_enforcer,
    mfa_service=mfa_service,
    abuse_detector=abuse_detector,
    risk_engine=risk_engine,
    trust_engine=trust_engine,
    audit_binder=audit_binder
)

# Make authorization decision
security_decision = await orchestrator.authorize_secret_access(
    user_id="user@company.com",
    credential_id="prod-db-secret",
    user_roles=["developer", "senior"]
)

# Handle decision
if security_decision.allowed:
    secret_value = await fetch_secret_from_vault()
    return secret_value
elif security_decision.frozen:
    # Account frozen - security incident detected
    raise FrozenAccountException(f"Account {user_id} is frozen")
elif security_decision.blocked:
    # Temporarily blocked - cooldown period active
    raise TemporarilBlockedException("Access temporarily blocked due to abuse pattern")
elif security_decision.requires_mfa:
    # MFA required - challenge user
    raise MFAElevationRequiredException("MFA elevation required")
else:
    # Denied for other reasons
    raise AccessDeniedException(f"Access denied: {security_decision.reason}")
```

---

## SecurityDecision Object

### Structure

```python
@dataclass(frozen=True)
class SecurityDecision:
    allowed: bool = False                    # ✓ Access allowed
    requires_mfa: bool = False               # ⚠ MFA needed
    blocked: bool = False                    # ✗ Temporarily blocked
    frozen: bool = False                     # ⛔ Permanently frozen
    reason: SecurityDecisionReason = ...     # Why decision was made
    risk_score: float = 0.0                  # Risk 0-100
    trust_level: str = None                  # e.g., "NORMAL", "ELEVATED_RISK"
    audit_events: List[str] = []            # Audit trail (step-by-step)
    timestamp: str = None                    # When decision was made (UTC)
```

### Example Decision Objects

**Allowed Decision:**
```python
SecurityDecision(
    allowed=True,
    reason=SecurityDecisionReason.ALLOWED_LOW_RISK,
    risk_score=15.0,
    trust_level="NORMAL",
    audit_events=[
        "TRUST_STATE:NORMAL",
        "RBAC:ALLOWED",
        "ABUSE_CHECK:PASSED",
        "RISK:15.0",
        "AUTHORIZATION:ALLOWED"
    ],
    timestamp="2025-01-15T14:23:45.123456"
)
```

**Blocked Decision:**
```python
SecurityDecision(
    blocked=True,
    reason=SecurityDecisionReason.TEMPORARY_BLOCK_HIGH_RISK,
    risk_score=78.5,
    trust_level="ELEVATED_RISK",
    audit_events=[
        "TRUST_STATE:NORMAL",
        "RBAC:ALLOWED",
        "ABUSE_CHECK:PASSED",
        "RISK:78.5",
        "TRUST:TEMP_BLOCK:ELEVATED_RISK"
    ],
    timestamp="2025-01-15T14:24:12.654321"
)
```

**Frozen Decision:**
```python
SecurityDecision(
    frozen=True,
    reason=SecurityDecisionReason.FROZEN_CRITICAL_RISK,
    risk_score=95.0,
    trust_level="FROZEN",
    audit_events=[
        "TRUST_STATE:NORMAL",
        "RBAC:ALLOWED",
        "ABUSE_CHECK:PASSED",
        "RISK:95.0",
        "TRUST:FREEZE:FROZEN"
    ],
    timestamp="2025-01-15T14:25:00.789012"
)
```

---

## Decision Reasons (SecurityDecisionReason Enum)

### ✅ Allowed (Access Granted)

| Reason | Meaning | Typical Use Case |
|--------|---------|-----------------|
| `ALLOWED_LOW_RISK` | Standard approval | Normal user, normal risk profile |
| `ALLOWED_ELEVATED_SESSION` | Approved via elevation | Senior admin, elevated context |

### ⚠️ Requires MFA (Challenge User)

| Reason | Meaning | Action Required |
|--------|---------|-----------------|
| `REQUIRES_MFA_ELEVATED_RISK` | MFA needed due to risk | User must complete MFA challenge |
| `REQUIRES_MFA_POLICY` | MFA mandated by policy | User must complete MFA challenge |

### ✗ Blocked (Temporarily Denied)

| Reason | Meaning | Duration | Recovery |
|--------|---------|----------|----------|
| `TEMPORARY_BLOCK_HIGH_RISK` | Risk threshold exceeded | Minutes to hours | Risk score must decline |
| `TEMPORARY_BLOCK_ABUSE` | Abuse pattern detected | Minutes to hours | Cooldown timer expires |

### ⛔ Frozen (Permanently Denied)

| Reason | Meaning | Resolution | Operator Action |
|--------|---------|-----------|-----------------|
| `FROZEN_CRITICAL_RISK` | Critical risk detected | Manual intervention | Admin unlock required |
| `FROZEN_POLICY_VIOLATION` | Policy violation | Manual intervention | Admin unlock required |

### ❌ Denied (Permanently Rejected)

| Reason | Meaning | Fix |
|--------|---------|-----|
| `DENIED_RBAC_INSUFFICIENT_PRIVILEGE` | Insufficient permissions | Grant role/permission |
| `DENIED_TRUST_FROZEN` | Account trust frozen | Admin unlock |
| `DENIED_RISK_CRITICAL` | Risk score critical | Risk must decline |
| `DENIED_ABUSE_DETECTED` | Abuse detected | Must wait cooldown |
| `DENIED_ELEVATED_ACCESS_REQUIRED` | Elevation required | Request elevation |

---

## Decision Flow Diagram

```
User Request
    ↓
┌─────────────────────────────┐
│ STEP 1: Trust State Check   │
│ - Is account frozen?        │
└─────────┬───────────────────┘
          │ FROZEN?
          ├─→ YES: Return FROZEN decision
          │ NO: Continue to Step 2
          │
┌─────────▼───────────────────┐
│ STEP 2: RBAC Check          │
│ - Does user have role?      │
└─────────┬───────────────────┘
          │ ALLOWED?
          ├─→ NO: Return DENIED_RBAC decision
          │ YES: Continue to Step 3
          │
┌─────────▼───────────────────┐
│ STEP 3: Abuse Detection     │
│ - Abnormal access pattern?  │
└─────────┬───────────────────┘
          │ CLEAN?
          ├─→ NO: Return BLOCKED_ABUSE decision
          │ YES: Continue to Step 4
          │
┌─────────▼───────────────────┐
│ STEP 4: Risk Assessment     │
│ - Calculate risk score      │
│ - risk_score is now set     │
└─────────┬───────────────────┘
          │
┌─────────▼───────────────────┐
│ STEP 5: Trust Engine Check  │
│ - Evaluate against risk     │
└─────────┬───────────────────┘
          │ Trust Action?
          ├─→ FREEZE: Return FROZEN_CRITICAL decision
          ├─→ TEMP_BLOCK: Return BLOCKED_RISK decision
          ├─→ REQUIRE_MFA: Continue to Step 6
          │ ALLOW: Continue to Step 7
          │
┌─────────▼───────────────────┐
│ STEP 6: MFA Elevation Check │
│ - Does user have session?   │
└─────────┬───────────────────┘
          │ HAS SESSION?
          ├─→ NO: Return REQUIRES_MFA decision
          │ YES: Continue to Step 7
          │
┌─────────▼───────────────────┐
│ STEP 7: All Passed          │
│ Return ALLOWED decision     │
└─────────┬───────────────────┘
          │
          ↓
Return SecurityDecision to caller
```

---

## Integration Examples

### Example 1: Basic Service Integration

```python
from modules.credentials.services import CredentialService

# Service already has orchestrator injected
credential_service = CredentialService(
    security_orchestrator=orchestrator,
    trust_engine=trust_engine
)

# Call get_with_secret - orchestrator runs internally
try:
    secret_data = await credential_service.get_with_secret(
        credential_id="prod-db-secret",
        user_id="user@company.com"
    )
    print(f"Secret obtained: {secret_data.name}")
except AccessDeniedException as e:
    print(f"Access denied: {e}")
except TemporarilyBlockedException as e:
    print(f"Temporarily blocked: {e}")
except MFAElevationRequiredException as e:
    print(f"MFA required: {e}")
```

### Example 2: Direct Orchestrator Testing

```python
# For testing or batch operations
decision = await orchestrator.authorize_secret_access(
    user_id="admin@company.com",
    credential_id="prod-db-secret",
    user_roles=["admin", "security"]
)

print(f"Decision: {decision.allowed}")
print(f"Reason: {decision.reason}")
print(f"Risk Score: {decision.risk_score}")
print(f"Trust Level: {decision.trust_level}")
print(f"Audit Events: {decision.audit_events}")
```

### Example 3: Audit Trail Analysis

```python
# Extract detailed audit from decision
decision = await orchestrator.authorize_secret_access(...)

for event in decision.audit_events:
    print(f"  {event}")

# Output example:
#   TRUST_STATE:NORMAL
#   RBAC:ALLOWED
#   ABUSE_CHECK:PASSED
#   RISK:42.5
#   TRUST:REQUIRE_MFA:ELEVATED_RISK
#   MFA_REQUIRED:NO_ELEVATION
```

### Example 4: Risk-Based Decision Handling

```python
decision = await orchestrator.authorize_secret_access(...)

if decision.risk_score > 75:
    print(f"⚠️ HIGH RISK ACCESS ({decision.risk_score})")
    
    if decision.frozen:
        # Escalate to security team
        await escalate_to_security_team(decision)
    elif decision.blocked:
        # Wait for cooldown
        print("Access temporarily blocked - retry in 30 minutes")
    elif decision.requires_mfa:
        # Challenge user
        await send_mfa_challenge(user_id)
        
elif decision.risk_score > 50:
    print(f"⚠️ MEDIUM RISK ACCESS ({decision.risk_score})")
    if decision.requires_mfa:
        await send_mfa_challenge(user_id)
    else:
        proceed_with_access()
else:
    print(f"✓ LOW RISK ACCESS ({decision.risk_score})")
    proceed_with_access()
```

### Example 5: Immutability Verification

```python
decision = await orchestrator.authorize_secret_access(...)

# Attempt to modify (will fail)
try:
    decision.allowed = False  # ERROR: frozen dataclass
except Exception as e:
    print(f"Cannot modify decision: {e}")

# Verify immutability with deepcopy
from copy import deepcopy
decision_copy = deepcopy(decision)
assert decision == decision_copy
assert decision is not decision_copy
```

---

## Component Interaction Matrix

### Who Calls What

```
┌────────────────────────────────────────────────────────┐
│          CredentialSecurityOrchestrator                │
├────────────────────────────────────────────────────────┤
│                                                        │
│  authorize_secret_access()                             │
│  ├→ TrustEngine.get_state()           [Step 1]         │
│  ├→ RBACEnforcer.enforce_or_raise()   [Step 2]         │
│  ├→ AbuseDetector.check_pattern()    [Step 3]          │
│  ├→ RiskEngine.assess()               [Step 4]         │
│  ├→ TrustEngine.evaluate()            [Step 5]         │
│  ├→ MFAService.elevation_*            [Step 6]         │
│  └→ AuditBinder.append_event()        [Audit]          │
│                                                        │
│  _audit_access_allowed()                               │
│  └→ AuditBinder.append_event()                         │
│                                                        │
│  _audit_access_denied()                                │
│  └→ AuditBinder.append_event()        [Async]          │
│                                                        │
└────────────────────────────────────────────────────────┘
```

---

## Configuration & Tuning

### Orchestrator with Subset of Components

```python
# RBAC-only (for testing)
orchestrator = CredentialSecurityOrchestrator(
    rbac_enforcer=rbac_enforcer
)

# RBAC + Risk (no MFA)
orchestrator = CredentialSecurityOrchestrator(
    rbac_enforcer=rbac_enforcer,
    risk_engine=risk_engine,
    trust_engine=trust_engine
)

# Full stack (all 5 components)
orchestrator = CredentialSecurityOrchestrator(
    rbac_enforcer=rbac_enforcer,
    mfa_service=mfa_service,
    abuse_detector=abuse_detector,
    risk_engine=risk_engine,
    trust_engine=trust_engine,
    audit_binder=audit_binder
)
```

### Trust Engine Configuration

```python
from core.security.trust.trust_state import TrustConfigs

# Available configurations
STRICT      # Aggressive trust decay, quick freeze
BALANCED    # Default, moderate protection
PRODUCTION  # Lenient, high availability
AGGRESSIVE  # Paranoid, frequent MFA

# Initialize with preferred config
trust_engine = TrustEngine(
    config=TrustConfigs.BALANCED,
    audit_binder=audit_binder
)
```

---

## Telemetry & Monitoring

### Decision Counters

```python
from dataclasses import Counter

# Track decisions
allowed_count = 0
mfa_required_count = 0
blocked_count = 0
frozen_count = 0
denied_count = 0

async for event in orchestrator_events:
    decision = event.security_decision
    
    if decision.allowed:
        allowed_count += 1
    elif decision.requires_mfa:
        mfa_required_count += 1
    elif decision.blocked:
        blocked_count += 1
    elif decision.frozen:
        frozen_count += 1
    else:
        denied_count += 1

print(f"Decisions: {allowed_count} allowed, {mfa_required_count} MFA, "
      f"{blocked_count} blocked, {frozen_count} frozen, {denied_count} denied")
```

### Risk Score Distribution

```python
import statistics

risk_scores = []

for event in events:
    decision = event.security_decision
    if decision.risk_score:
        risk_scores.append(decision.risk_score)

if risk_scores:
    print(f"Risk Score Stats:")
    print(f"  Min: {min(risk_scores):.1f}")
    print(f"  Max: {max(risk_scores):.1f}")
    print(f"  Mean: {statistics.mean(risk_scores):.1f}")
    print(f"  Median: {statistics.median(risk_scores):.1f}")
```

### Audit Trail Export

```python
# Export full audit trail for each decision
export_data = []

for event in events:
    decision = event.security_decision
    
    export_data.append({
        "timestamp": decision.timestamp,
        "user_id": event.user_id,
        "credential_id": event.credential_id,
        "decision": {
            "allowed": decision.allowed,
            "reason": decision.reason.value,
            "risk_score": decision.risk_score,
            "trust_level": decision.trust_level
        },
        "audit_events": decision.audit_events
    })

# Write to auditable log
import json
with open("security_audit.jsonl", "w") as f:
    for record in export_data:
        f.write(json.dumps(record) + "\n")
```

---

## Troubleshooting

### Decision is "allowed" but should be "blocked"

**Possible Causes:**
1. Abuse detector not called (not injected?)
   - Check: `orchestrator.abuse` is not None
2. Risk score below block threshold
   - Check: `decision.risk_score` value
3. Trust engine not configured correctly
   - Check: `TrustConfigs` used in `TrustEngine`

**Debug:**
```python
decision = await orchestrator.authorize_secret_access(...)
print(f"Abuse detector: {orchestrator.abuse is not None}")
print(f"Risk score: {decision.risk_score}")
print(f"Audit events: {decision.audit_events}")
for event in decision.audit_events:
    print(f"  - {event}")
```

### All requests return "denied"

**Possible Causes:**
1. RBAC policy too strict
   - Check: User has required role
2. Account frozen
   - Check: `TrustState.level == FROZEN`
3. Abuse detector always blocking
   - Check: Abuse patterns configured correctly

**Debug:**
```python
print(f"User roles: {user_roles}")
print(f"Trust state: {await trust_engine.get_state(user_id)}")
print(f"Risk score: {await risk_engine.assess(user_id)}")
```

### MFA required but session exists

**Possible Causes:**
1. Session expired
   - Check: `elevation_session_manager.session_ttl`
2. Risk threshold triggers MFA always
   - Check: `TrustPolicy` configuration for REQUIRE_MFA action
3. Risk score above MFA threshold
   - Check: `risk_engine.mfa_threshold`

**Debug:**
```python
has_session = await mfa.elevation_session_manager.has_active_session(user_id)
session_details = await mfa.elevation_session_manager.get_session(user_id)
print(f"Has session: {has_session}")
print(f"Session expires: {session_details.expires_at if session_details else 'N/A'}")
```

---

## Best Practices

### ✅ DO

- ✅ Check `security_decision.allowed` before granting access
- ✅ Log `decision.audit_events` for every request
- ✅ Treat `frozen` accounts as security incidents
- ✅ Implement retry logic for `blocked` state
- ✅ Challenge users with MFA when `requires_mfa=True`
- ✅ Use orchestrator for ALL secret access paths
- ✅ Monitor `risk_score` trends over time
- ✅ Escalate frozen accounts to security team immediately

### ❌ DON'T

- ❌ Ignore orchestrator and use legacy security checks
- ❌ Treat `requires_mfa` same as `denied`
- ❌ Retry immediately on `blocked` (wait for cooldown)
- ❌ Modify SecurityDecision after creation (it's frozen)
- ❌ Bypass orchestrator for "privileged" users
- ❌ Log full `audit_events` in user-facing messages
- ❌ Assume old security checks still work
- ❌ Deploy without running full test suite

---

## References

- **Main Documentation**: `STEP_17_10_COMPLETION_REPORT.md`
- **Trust Engine**: Step 17.9 (automatic recovery)
- **Risk Engine**: Step 17.8 (adaptive scoring)
- **Abuse Detection**: Step 17.7 (pattern analysis)
- **MFA Service**: Step 17.6 (identity verification)
- **RBAC**: Steps 17.1-17.5 (access control)

---

## Example: Complete Workflow

```python
# 1. Initialize orchestrator with all components
orchestrator = CredentialSecurityOrchestrator(
    rbac_enforcer=rbac_enforcer,
    mfa_service=mfa_service,
    abuse_detector=abuse_detector,
    risk_engine=risk_engine,
    trust_engine=trust_engine,
    audit_binder=audit_binder
)

# 2. User requests secret access
user_id = "bob@company.com"
credential_id = "prod-api-key"
user_roles = ["developer"]

# 3. Make security decision
security_decision = await orchestrator.authorize_secret_access(
    user_id=user_id,
    credential_id=credential_id,
    user_roles=user_roles
)

# 4. Examine decision
print(f"Allowed: {security_decision.allowed}")
print(f"Risk Score: {security_decision.risk_score:.1f}")
print(f"Trust Level: {security_decision.trust_level}")
print(f"Reason: {security_decision.reason.value}")

# 5. Handle based on outcome
if security_decision.allowed:
    # Grant access
    secret = await vault.get_secret(credential_id)
    return secret
    
elif security_decision.requires_mfa:
    # Challenge user with MFA
    challenge = await mfa.create_challenge(user_id)
    return {"require_mfa": True, "challenge_id": challenge.id}
    
elif security_decision.blocked:
    # Wait for cooldown
    return {"error": "access_temporarily_blocked", "retry_after_seconds": 1800}
    
elif security_decision.frozen:
    # Escalate to security team
    await security_team.escalate(user_id, "Account frozen")
    return {"error": "account_frozen", "contact_security": True}
    
else:
    # Other denial
    return {"error": "access_denied", "reason": security_decision.reason.value}
```

---

**Quick Reference Version**: v1.0  
**Last Updated**: Step 17.10 Completion  
**Status**: Production Ready ✅
