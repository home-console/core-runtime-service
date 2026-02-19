# Step 19: Rotation Strategies - Quick Reference Guide

**At a Glance:**  
Plugin-based rotation strategies with dynamic registration. Three built-in strategies: vault-only, agent-orchestrated, and webhook-based.

---

## Quick Start (5 minutes)

### 1. Initialize Registry & Strategies

```python
from modules.credentials.rotation import (
    StrategyRegistry,
    GenerateNewSecretStrategy,
    AgentPushStrategy,
    WebhookRotationStrategy,
)

# Create and populate registry
registry = StrategyRegistry()
await registry.register(GenerateNewSecretStrategy())
await registry.register(AgentPushStrategy())
await registry.register(WebhookRotationStrategy())
```

### 2. Create Executor

```python
from modules.credentials.rotation import RotationExecutorV2

executor = RotationExecutorV2(
    vault_store=vault,           # Vault backend
    repository=repo,             # Credential repository
    audit_binder=audit,          # Audit logging
    strategy_registry=registry,  # Plugin registry
    trust_engine=trust,          # Account freezing
    risk_engine=risk,            # Risk escalation
)
```

### 3. Execute Rotation

```python
# Execute (strategy auto-selected from policy)
new_ref, new_version = await executor.execute_rotation(
    credential_id="api_key_1",
    policy=RotationPolicy.daily(),
    current_version=1,
    extra_context={"operation_manager": op_manager},  # For agent strategy
)
```

---

## Strategy Selection

**Policy → Strategy Mapping:**

| Policy Strategy | Selects | Best For |
|-----------------|---------|----------|
| `GENERATE_NEW_SECRET` | GenerateNewSecretStrategy | API keys, tokens, passwords |
| `AGENT_PUSH` | AgentPushStrategy | Database creds, SSH keys |
| `WEBHOOK_CALLBACK` | WebhookRotationStrategy | Third-party integrations |
| `MANUAL` | (None - direct storage) | Emergency credentials |

---

## Strategy APIs

### Built-In Strategies

#### GenerateNewSecretStrategy

```python
strategy = GenerateNewSecretStrategy()

# Properties
strategy.type = RotationStrategyType.GENERATE_NEW_SECRET
strategy.name = "Vault-based Secret Generation"

# Execute (generates secret, stores in vault)
result = await strategy.execute(context)
# result.success = True
# result.new_secret_ref = "api_key_1:v2"
# result.new_version = 2
```

**When to Use:**
- API keys and tokens
- Session secrets
- One-time passwords
- Any vault-stored credential

**Advantages:**
- Fast (no external calls)
- Self-contained
- Secure (CSPRNG entropy)
- No network failures

#### AgentPushStrategy

```python
strategy = AgentPushStrategy()

# Execute (coordinates with remote agent)
result = await strategy.execute(context)
# 1. Creates RotationOperation
# 2. Waits for agent (300s timeout)
# 3. Validates response
# 4. Stores in vault
```

**When to Use:**
- Database credentials (MySQL, PostgreSQL, Oracle)
- SSH keys
- System accounts
- Any credential that agent must rotate

**Context Extra Params:**
```python
context.extra_params = {
    "operation_manager": op_manager,  # REQUIRED for agent strategy
    "target_system": "mysql_prod_01",  # Optional parameter for agent
    "rotation_method": "user_password",  # Optional parameter for agent
}
```

**Agent Operation:**
```json
{
    "operation_type": "credential_rotation",
    "credential_id": "db_cred_prod",
    "idempotency_token": "abc123def456...",
    "target_system": "mysql_prod_01",
    "extra_params": {...}
}
```

#### WebhookRotationStrategy

```python
strategy = WebhookRotationStrategy()

# Execute (calls external webhook)
result = await strategy.execute(context)
# 1. Validating webhook URL
# 2. POST to webhook
# 3. Extracts secret from response
# 4. Stores in vault
```

**When to Use:**
- Third-party secret managers
- Custom rotation workflows
- External team integrations
- SAS vendor passwords

**Webhook Configuration:**
```python
# Per-credential webhook URL
credential.metadata["webhook_url"] = "https://third-party.com/rotate"

# Or default per credential type
DEFAULT_WEBHOOK_URLS = {
    "salesforce_token": "https://salesforce-managed.com/rotate",
    "datadog_key": "https://datadog-managed.com/rotate",
}
```

---

## Rotating Credentials

### One-Time Rotation

```python
# Manual rotation now
new_ref, new_version = await executor.execute_rotation(
    credential_id="api_key_1",
    policy=RotationPolicy.immediate(),  # No schedule
    current_version=1,
    extra_context={
        "operation_manager": op_manager,
        "reason": "Security incident response",
    }
)

print(f"Rotated to version {new_version}: {new_ref}")
```

### Scheduled Rotation

```python
# Rotation via scheduler (uses policy from credential)
scheduler.schedule_rotation(credential_id="api_key_1")
# Executor runs with strategy from credential.rotation_policy.strategy
```

### Manual Secret Storage

```python
# User provides secret directly (emergency only)
new_ref, new_version = await executor.execute_manual_rotation(
    credential_id="api_key_1",
    secret_value="provided_by_user",
    current_version=1,
)
```

---

## Error Handling

### Execution Errors

```python
try:
    result = await executor.execute_rotation(cred_id, policy, version)
except RotationNotAllowedError as e:
    # Account frozen - skip rotation
    logger.warning(f"Rotation skipped (frozen): {e.reason}")

except StrategyExecutionError as e:
    # Strategy failed
    logger.error(f"Rotation failed: {e.message}")
    
    # Check escalation flags
    if e.should_freeze_account:
        logger.critical("Account frozen due to rotation failure")
    
    if e.should_escalate_risk:
        logger.critical("Risk escalated due to rotation failure")

except StrategyNotRegisteredError as e:
    # Strategy not available
    logger.error(f"Strategy not available: {e.strategy_type}")
```

### Strategy Validation

```python
# Pre-flight check
if not await strategy.validate(context):
    logger.warning("Strategy cannot execute - prerequisites not met")

# Check account frozen
if await trust_engine.get_state(cred_id).is_frozen:
    logger.warning("Cannot rotate - account frozen")
```

---

## Registry Management

### Adding Strategies

```python
registry = StrategyRegistry()

# Built-in strategy
await registry.register(GenerateNewSecretStrategy())

# Custom strategy
class MySQLRotationStrategy(RotationStrategyBase):
    def __init__(self):
        super().__init__(RotationStrategyType.AGENT_PUSH, "MySQL Rotation")
    
    async def execute(self, context):
        # Custom logic
        return RotationResult(...)

await registry.register(MySQLRotationStrategy())
```

### Checking Registry

```python
# List all strategies
strategies = await registry.list_strategies()
# {'GENERATE_NEW_SECRET': 'Vault-based Secret Generation', ...}

# Check if strategy available
if await registry.is_registered("AGENT_PUSH"):
    strategy = await registry.get("AGENT_PUSH")

# Get or error
try:
    strategy = await registry.get_or_fail(RotationStrategyType.WEBHOOK_CALLBACK)
except StrategyNotFoundError:
    logger.error("Webhook strategy not registered")
```

### Hot Swapping Strategies

```python
# Unregister old version
await registry.unregister(RotationStrategyType.AGENT_PUSH)

# Register new version
await registry.register(AgentPushStrategyV2())

# Future rotations use new strategy
# In-flight rotations complete with old version
```

---

## Custom Strategies

### Minimal Strategy

```python
from modules.credentials.rotation import (
    RotationStrategyBase,
    RotationStrategyType,
    RotationStrategyContext,
    RotationResult,
)

class SimpleCustomStrategy(RotationStrategyBase):
    def __init__(self):
        super().__init__(
            type=RotationStrategyType.GENERATE_NEW_SECRET,
            name="My Custom Strategy",
        )
    
    async def execute(self, context: RotationStrategyContext) -> RotationResult:
        # Custom rotation logic
        new_secret = generate_secret()
        
        # Store in vault
        new_ref = await context.vault_store.store(
            context.credential_id,
            new_secret,
        )
        
        # Return result
        return RotationResult(success=True, new_secret_ref=new_ref)
    
    async def validate(self, context: RotationStrategyContext) -> bool:
        # Pre-flight check
        return True  # Ready to execute
    
    async def rollback(self, context, failed_version, prev_ref):
        # Recovery from failure
        return True  # Success
```

### Full Strategy with Error Handling

```python
class RobustCustomStrategy(RotationStrategyBase):
    def __init__(self):
        super().__init__(RotationStrategyType.WEBHOOK_CALLBACK, "Robust Strategy")
    
    async def execute(self, context):
        try:
            # Validation
            if not await self.validate(context):
                return RotationResult(
                    success=False,
                    error_message="Prerequisites not met",
                    error_code="INVALID_CONTEXT",
                    should_escalate_risk=False,
                )
            
            # Rotation logic
            new_secret = await self._perform_rotation(context)
            
            # Store
            new_ref = await context.vault_store.store(
                context.credential_id,
                new_secret,
            )
            
            # Audit
            await context.audit_binder.append_event({
                "event_type": "credential_rotated_custom",
                "credential_id": context.credential_id,
                "new_version": context.current_version + 1,
                "strategy": "RobustCustomStrategy",
            })
            
            return RotationResult(
                success=True,
                new_secret_ref=new_ref,
                new_version=context.current_version + 1,
            )
        
        except Exception as e:
            return RotationResult(
                success=False,
                error_message=str(e),
                error_code="ROTATION_FAILED",
                should_freeze_account=True,
                should_escalate_risk=True,
            )
    
    async def validate(self, context):
        return True  # Implement your validation
    
    async def rollback(self, context, failed_version, prev_ref):
        logger.info(f"Rolling back rotation of {context.credential_id}")
        return True
```

---

## Audit Logging

### Logged Events

```json
{
    "event_type": "credential_rotation_started",
    "credential_id": "api_key_1",
    "strategy_type": "GENERATE_NEW_SECRET",
    "initial_version": 1,
    "timestamp": "2026-02-15T10:30:00Z"
}

{
    "event_type": "credential_rotated",
    "credential_id": "api_key_1",
    "new_version": 2,
    "new_secret_ref": "api_key_1:v2",
    "strategy_type": "GENERATE_NEW_SECRET",
    "timestamp": "2026-02-15T10:30:01Z"
}

{
    "event_type": "credential_rotation_failed",
    "credential_id": "api_key_1",
    "error_code": "AGENT_TIMEOUT",
    "error_message": "Agent did not respond within 300s",
    "escalated_to_risk": true,
    "account_frozen": false,
    "timestamp": "2026-02-15T10:35:02Z"
}
```

### Secrets Never Logged
- ❌ Secret values
- ❌ Secret content
- ❌ Entropy inputs
- ✅ Secret references (e.g., "api_key_1:v2")
- ✅ Operation IDs
- ✅ Strategy type
- ✅ Success/failure status

---

## Performance Tips

### Optimize for Speed
```python
# Use GenerateNewSecretStrategy for fast rotations (no network)
policy = RotationPolicy(
    rotation_strategy=RotationStrategy.GENERATE_NEW_SECRET,
    interval_minutes=60,
)
```

### Batch Operations
```python
# Multiple credentials with same strategy
credentials = [cred1, cred2, cred3]

tasks = [
    executor.execute_rotation(c.id, c.policy, c.version)
    for c in credentials
]

results = await asyncio.gather(*tasks)
```

### Handle Timeouts Gracefully
```python
# Agent strategy has 300s timeout
try:
    result = await asyncio.wait_for(
        executor.execute_rotation(cred_id, policy, version),
        timeout=320,  # Slightly more than strategy timeout
    )
except asyncio.TimeoutError:
    logger.error("Rotation exceeded timeout")
    # Handle escalation
```

---

## Troubleshooting

### Strategy Not Registered
```python
# Problem:
await executor.execute_rotation(cred_id, policy, version)
# StrategyNotRegisteredError: Strategy AGENT_PUSH not found

# Solution:
await registry.register(AgentPushStrategy())
```

### Agent Timeout
```python
# Problem: Agent doesn't respond
# Log: "Agent did not respond within 300s"

# Solution: Check agent process, network connectivity
# Escalation: Account frozen, rotation deferred
```

### Webhook Returns Error
```python
# Problem:
# WebhookRotationStrategy.execute() → error_code: "WEBHOOK_FAILED"

# Solution:
# 1. Verify webhook URL in credential metadata
# 2. Check webhook endpoint availability
# 3. Review webhook logs
```

### Vault Storage Failure
```python
# Problem: Vault unreachable
# All strategies fail at store step

# Solution:
# 1. Check vault connectivity
# 2. Verify vault health
# 3. Check token permissions
```

---

## Environment Variables

```bash
# Optional: Custom vault backend
VAULT_BACKEND_URL=https://vault.production.com

# Optional: Agent operation timeout (milliseconds)
AGENT_ROTATION_TIMEOUT_MS=300000

# Optional: Webhook rotation timeout
WEBHOOK_ROTATION_TIMEOUT_MS=60000

# Required for security audit (logging)
AUDIT_LOG_DESTINATION=syslog://audit-server:514
```

---

## See Also

- [Strategy API Reference](#strategy-apis)
- [Integration Guide](STEP_19_INTEGRATION_GUIDE.md)
- [Complete Report](STEP_19_COMPLETION_REPORT.md)
- [Step 18: Rotation Engine](STEP_18_COMPLETION_REPORT.md)

---

## Cheat Sheet

```python
# Initialize
registry = StrategyRegistry()
await registry.register(GenerateNewSecretStrategy())
executor = RotationExecutorV2(vault, repo, audit, registry, trust, risk)

# Rotate
result = await executor.execute_rotation(cred_id, policy, version)

# Custom strategy
class MyStrategy(RotationStrategyBase):
    async def execute(self, context): ...
    async def validate(self, context): ...
    async def rollback(self, context, failed_version, prev_ref): ...

# Register custom
await registry.register(MyStrategy())

# Error handling
try:
    await executor.execute_rotation(...)
except RotationNotAllowedError:
    # Frozen account
except StrategyExecutionError as e:
    if e.should_freeze_account: ...
    if e.should_escalate_risk: ...
```

---

**Status: ✅ QUICK REFERENCE COMPLETE**
