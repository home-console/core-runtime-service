# Step 19: Rotation Strategies - Integration Guide

**Purpose:** How to integrate Step 19's plugin-based rotation strategies with the CredentialModule  
**Audience:** Backend team, DevOps, SRE  
**Updated:** February 15, 2026

---

## Quick Integration (15 minutes)

### Step 1: Initialize the Strategy Registry

```python
# In your CredentialModule initialization
from modules.credentials.rotation import (
    StrategyRegistry,
    GenerateNewSecretStrategy,
    AgentPushStrategy,
    WebhookRotationStrategy,
)

# Create registry
strategy_registry = StrategyRegistry()

# Register built-in strategies
await strategy_registry.register(GenerateNewSecretStrategy())
await strategy_registry.register(AgentPushStrategy())
await strategy_registry.register(WebhookRotationStrategy())
```

### Step 2: Create Executor with Registry

```python
from modules.credentials.rotation import RotationExecutorV2

# Create executor (pass registry instead of hardcoded logic)
rotation_executor = RotationExecutorV2(
    vault_store=vault_backend,           # From Step 14
    repository=credential_repository,    # From Step 15
    audit_binder=audit_system,           # From Step 17
    strategy_registry=strategy_registry, # NEW: Step 19
    trust_engine=trust_engine,           # From Step 16
    risk_engine=risk_engine,             # From Step 16
)
```

### Step 3: Use Executor (No Code Changes)

```python
# Rotation works exactly like Step 18
new_ref, new_version = await rotation_executor.execute_rotation(
    credential_id="api_key_prod",
    policy=RotationPolicy.daily(),
    current_version=1,
    extra_context={},
    # For AgentPushStrategy:
    extra_context={"operation_manager": operation_manager},
)
```

---

## Full Integration Example

### CredentialModule Initialization

```python
"""
core/credentials/module.py

Integration of Step 19 strategies with CredentialModule.
"""

from modules.credentials.rotation import (
    StrategyRegistry,
    RotationExecutorV2,
    GenerateNewSecretStrategy,
    AgentPushStrategy,
    WebhookRotationStrategy,
)
from modules.credentials.rotation.policy import RotationPolicy
from core.vault import VaultStore
from core.audit import AuditBinder
from core.trust import TrustEngine
from core.risk import RiskEngine
from core.repository import CredentialRepository
from execution.operation_manager import OperationManager


class CredentialModule:
    """Main credential management module with Step 19 integration."""
    
    def __init__(
        self,
        vault_store: VaultStore,
        repository: CredentialRepository,
        audit_binder: AuditBinder,
        trust_engine: TrustEngine,
        risk_engine: RiskEngine,
        operation_manager: OperationManager,
    ):
        self.vault_store = vault_store
        self.repository = repository
        self.audit_binder = audit_binder
        self.trust_engine = trust_engine
        self.risk_engine = risk_engine
        self.operation_manager = operation_manager
        
        # Step 19: Initialize strategy registry
        self.strategy_registry = None
        self.rotation_executor = None
    
    async def initialize(self):
        """Initialize module and strategies."""
        
        # 1. Create plugin registry
        self.strategy_registry = StrategyRegistry()
        
        # 2. Register built-in strategies
        await self.strategy_registry.register(GenerateNewSecretStrategy())
        await self.strategy_registry.register(AgentPushStrategy())
        await self.strategy_registry.register(WebhookRotationStrategy())
        
        # 3. Create executor with registry
        self.rotation_executor = RotationExecutorV2(
            vault_store=self.vault_store,
            repository=self.repository,
            audit_binder=self.audit_binder,
            strategy_registry=self.strategy_registry,
            trust_engine=self.trust_engine,
            risk_engine=self.risk_engine,
        )
        
        return self
    
    async def rotate_credential(
        self,
        credential_id: str,
        force: bool = False,
    ) -> tuple[str, int]:
        """Rotate credential using appropriate strategy."""
        
        # Load credential
        credential = await self.repository.get_credential(credential_id)
        
        # Get rotation policy (policy defines strategy)
        policy = credential.rotation_policy
        
        # Execute rotation (strategy selected automatically)
        new_ref, new_version = await self.rotation_executor.execute_rotation(
            credential_id=credential_id,
            policy=policy,
            current_version=credential.current_version,
            extra_context={
                "operation_manager": self.operation_manager,  # For agent strategy
                "force": force,
            },
        )
        
        return new_ref, new_version
    
    async def add_custom_strategy(self, strategy):
        """Add custom rotation strategy dynamically."""
        await self.strategy_registry.register(strategy)
    
    async def shutdown(self):
        """Clean up resources."""
        # Strategies don't need cleanup (stateless)
        pass
```

### Usage in Application

```python
# app.py

from core.credentials import CredentialModule
from core.vault import VaultStore
from core.audit import AuditBinder
from core.trust import TrustEngine
from core.risk import RiskEngine
from core.repository import CredentialRepository
from execution.operation_manager import OperationManager


async def main():
    # Initialize dependencies
    vault = VaultStore.from_config()
    repo = CredentialRepository(db_connection)
    audit = AuditBinder(syslog_endpoint)
    trust = TrustEngine(audit)
    risk = RiskEngine(audit)
    op_manager = OperationManager(agent_registry)
    
    # Initialize credential module (includes Step 19)
    cred_module = CredentialModule(
        vault_store=vault,
        repository=repo,
        audit_binder=audit,
        trust_engine=trust,
        risk_engine=risk,
        operation_manager=op_manager,
    )
    await cred_module.initialize()
    
    # Rotate credential (strategy auto-selected from policy)
    new_ref, new_version = await cred_module.rotate_credential("api_key_prod")
    print(f"Rotated to {new_ref} (version {new_version})")
    
    # Shutdown
    await cred_module.shutdown()
```

---

## Integration Points

### 1. With OperationManager (For Agent Strategy)

**Required for AgentPushStrategy to work:**

```python
from execution.operation_manager import OperationManager

class AgentPushStrategy(RotationStrategyBase):
    async def execute(self, context):
        # Get OperationManager from extra_context
        op_manager = context.extra_params.get("operation_manager")
        
        if not op_manager:
            raise StrategyExecutionError("OperationManager required")
        
        # Create rotation operation
        operation = await op_manager.create_operation(
            operation_type="credential_rotation",
            target_agent="agent_001",
            payload={
                "credential_id": context.credential_id,
                "idempotency_token": self._get_idempotency_token(context),
            },
        )
        
        # Wait for completion
        result = await operation.wait_for_completion(timeout=300)
        
        # Validate and process result
        ...
```

**Integration:**
```python
extra_context = {
    "operation_manager": operation_manager,
    "target_agent": "mysql_prod_01_rotator",
}

new_ref, new_version = await executor.execute_rotation(
    "db_cred_prod",
    policy,
    version,
    extra_context=extra_context,
)
```

### 2. With Trust Engine (For Account Freezing)

**Pre-rotation check:**
```python
# In RotationStrategyBase.pre_execute_checks()
if context.trust_engine:
    state = await context.trust_engine.get_state(context.credential_id)
    if state.is_frozen:
        raise RotationNotAllowedError("Account frozen: " + state.freeze_reason)
```

**Post-failure escalation:**
```python
# In RotationExecutorV2.execute_rotation()
result = await strategy.execute(context)

if not result.success:
    if result.should_freeze_account and context.trust_engine:
        await context.trust_engine.freeze(context.credential_id)
```

### 3. With Risk Engine (For Risk Escalation)

**Escalation on strategy failure:**
```python
# All strategies can escalate risk
result = RotationResult(
    success=False,
    error_message="Agent timeout",
    error_code="AGENT_TIMEOUT",
    should_escalate_risk=True,  # Trigger risk escalation
)

# Executor handles escalation
if result.should_escalate_risk and context.risk_engine:
    await context.risk_engine.escalate(context.credential_id, reason="rotation_failure")
```

### 4. With Audit Binder (For Audit Trail)

**Automatic audit logging:**
```python
# Strategy execution is fully audited
await context.audit_binder.append_event({
    "event_type": "credential_rotation_started",
    "credential_id": context.credential_id,
    "strategy_type": self.type.value,
    "initial_version": context.current_version,
})

# Success
await context.audit_binder.append_event({
    "event_type": "credential_rotated",
    "credential_id": context.credential_id,
    "new_version": context.current_version + 1,
    "strategy_type": self.type.value,
})

# Failure
await context.audit_binder.append_event({
    "event_type": "credential_rotation_failed",
    "credential_id": context.credential_id,
    "error_code": result.error_code,
    "escalated_to_risk": result.should_escalate_risk,
})
```

### 5. With Vault Store (For Secret Storage)

**All strategies use vault for storage:**
```python
# Generate strategy
new_secret = generate_secret()
new_ref = await context.vault_store.store(
    context.credential_id,
    new_secret,
    version=context.current_version + 1,
)

# Agent strategy
agent_secret = result.secret_from_agent
new_ref = await context.vault_store.store_agent_rotation(
    context.credential_id,
    agent_secret,
    agent_id=agent_response.agent_id,
    version=context.current_version + 1,
)
```

### 6. With Repository (For Version Management)

**Credential update after rotation:**
```python
# In RotationExecutorV2.execute_rotation()
credential = await context.repository.get_credential(credential_id)

# Mutate (immutable pattern)
updated = credential.mutate(
    version=new_version,
    secret_ref=new_secret_ref,
    last_rotation=datetime.now(),
)

# Persist
await context.repository.update_credential(updated)
```

---

## Custom Strategy Integration

### Example: Database-Specific Strategy

```python
from modules.credentials.rotation import (
    RotationStrategyBase,
    RotationStrategyType,
    RotationStrategyContext,
    RotationResult,
)


class MySQLRotationStrategy(RotationStrategyBase):
    """MySQL user password rotation via OperationManager."""
    
    def __init__(self):
        super().__init__(
            type=RotationStrategyType.AGENT_PUSH,
            name="MySQL User Password Rotation",
        )
    
    async def execute(self, context: RotationStrategyContext) -> RotationResult:
        """Execute MySQL-specific rotation."""
        
        try:
            # Validate prerequisites
            if not await self.validate(context):
                return RotationResult(
                    success=False,
                    error_message="MySQL prerequisites not met",
                    error_code="MYSQL_INVALID_CONFIG",
                )
            
            # Get OperationManager
            op_manager = context.extra_params.get("operation_manager")
            
            # Create MySQL-specific operation
            operation = await op_manager.create_operation(
                operation_type="mysql_user_rotation",
                target_agent="mysql_rotation_agent",
                payload={
                    "database": context.extra_params.get("database", "default"),
                    "username": context.extra_params.get("username"),
                    "idempotency_token": self._get_token(context),
                },
            )
            
            # Wait for agent
            agent_result = await operation.wait_for_completion(timeout=60)
            
            # Extract new password
            new_password = agent_result.new_password
            
            # Store in vault
            new_ref = await context.vault_store.store(
                context.credential_id,
                new_password,
            )
            
            # Audit
            await context.audit_binder.append_event({
                "event_type": "credential_rotated_mysql",
                "credential_id": context.credential_id,
                "database": context.extra_params.get("database"),
                "new_version": context.current_version + 1,
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
                error_code="MYSQL_ROTATION_FAILED",
                should_escalate_risk=True,
                should_freeze_account=False,
            )
    
    async def validate(self, context):
        # Check MySQL config available
        return "database" in context.extra_params
    
    async def rollback(self, context, failed_version, prev_ref):
        # Restore old password
        op_manager = context.extra_params.get("operation_manager")
        default_password = await context.vault_store.get(prev_ref)
        
        operation = await op_manager.create_operation(
            operation_type="mysql_restore_password",
            payload={
                "database": context.extra_params.get("database"),
                "password": default_password,
            },
        )
        
        return await operation.wait_for_completion()
```

### Register Custom Strategy

```python
# In CredentialModule
class CredentialModule:
    async def initialize(self):
        # Register built-in strategies
        await self.strategy_registry.register(GenerateNewSecretStrategy())
        await self.strategy_registry.register(AgentPushStrategy())
        
        # Register custom strategies
        await self.strategy_registry.register(MySQLRotationStrategy())
        await self.strategy_registry.register(PostgreSQLRotationStrategy())
        await self.strategy_registry.register(OracleRotationStrategy())
```

### Use Custom Strategy in Policy

```python
credential = Credential(
    id="db_mysql_prod",
    rotation_policy=RotationPolicy(
        strategy=RotationStrategy.AGENT_PUSH,  # Selects MySQLRotationStrategy
        interval_minutes=24 * 60,
    ),
)
```

---

## Testing Integration

### Unit Test Example

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from modules.credentials.rotation import RotationExecutorV2, StrategyRegistry
from modules.credentials.rotation.strategies import MySQLRotationStrategy


@pytest.mark.asyncio
async def test_mysql_rotation_integration():
    """Test MySQL strategy integration with RotationExecutorV2."""
    
    # Setup mocks
    vault_store = AsyncMock()
    vault_store.store = AsyncMock(return_value="db_cred:v2")
    
    repository = AsyncMock()
    repository.get_credential = AsyncMock(
        return_value=MagicMock(
            id="db_mysql_prod",
            current_version=1,
            rotation_policy=MagicMock(strategy="AGENT_PUSH"),
        )
    )
    
    audit_binder = AsyncMock()
    operation_manager = AsyncMock()
    
    # Create registry with custom strategy
    registry = StrategyRegistry()
    await registry.register(MySQLRotationStrategy())
    
    # Create executor
    executor = RotationExecutorV2(
        vault_store=vault_store,
        repository=repository,
        audit_binder=audit_binder,
        strategy_registry=registry,
        trust_engine=AsyncMock(),
        risk_engine=AsyncMock(),
    )
    
    # Execute
    new_ref, new_version = await executor.execute_rotation(
        "db_mysql_prod",
        MagicMock(strategy="AGENT_PUSH"),
        current_version=1,
        extra_context={"operation_manager": operation_manager},
    )
    
    # Verify
    assert new_ref == "db_cred:v2"
    assert new_version == 2
    vault_store.store.assert_called_once()
```

---

## Deployment Checklist

- [ ] Strategy registry initialized
- [ ] All built-in strategies registered
- [ ] Custom strategies registered (if applicable)
- [ ] RotationExecutorV2 created with registry
- [ ] OperationManager configured for agent strategy
- [ ] Audit trail configured
- [ ] Trust engine initialized
- [ ] Risk engine initialized
- [ ] Tests passing
- [ ] Integration tests running
- [ ] Monitoring configured
- [ ] Documentation reviewed

---

## Troubleshooting Integration

### Strategy Not Found During Rotation

```python
# Problem: StrategyNotRegisteredError

# Solution:
# 1. Check strategy is registered in initialize()
await registry.register(GenerateNewSecretStrategy())

# 2. Check credential policy has correct strategy type
credential.rotation_policy.strategy = RotationStrategy.GENERATE_NEW_SECRET

# 3. Verify registry is injected in executor
executor = RotationExecutorV2(
    strategy_registry=registry,  # Make sure this is passed
    ...
)
```

### Agent Strategy Timeout

```python
# Problem: "Agent did not respond within 300s"

# Solution:
# 1. Check OperationManager is in extra_context
extra_context = {"operation_manager": operation_manager}

# 2. Verify agent is running
# 3. Check network connectivity
# 4. Increase timeout if needed (but 300s is typical)
```

### Audit Events Not Logged

```python
# Problem: No rotation events in audit trail

# Solution:
# 1. Verify audit_binder is configured
executor = RotationExecutorV2(
    audit_binder=audit_binder,  # Check this
    ...
)

# 2. Check audit destination (syslog, file, etc.)
# 3. Verify credentials for audit endpoint
```

---

## Performance Considerations

### Registry Lookup Performance
- **Complexity:** O(1) - dictionary lookup
- **No impact:** Can register/unregister without affecting active rotations

### Strategy Execution Timeline
```
GenerateNewSecretStrategy: ~10ms (no network)
AgentPushStrategy:         ~1-300s (agent-dependent)
WebhookRotationStrategy:   ~100ms-10s (endpoint-dependent)
```

### Concurrent Rotations
```python
# Safe for concurrent execution
tasks = [
    executor.execute_rotation(f"cred_{i}", policy, 1)
    for i in range(100)
]

results = await asyncio.gather(*tasks)
```

---

## Monitoring & Observability

### Key Metrics to Track

```python
# Registry size
num_strategies = len(await registry.list_strategies())

# Strategy usage
async def get_strategy_stats():
    return {
        "GENERATE_NEW_SECRET": 10,  # rotations this hour
        "AGENT_PUSH": 5,
        "WEBHOOK_CALLBACK": 2,
    }

# Rotation success rate
success_rate = (successful_rotations / total_rotations) * 100

# Average rotation time per strategy
avg_time_generate = mean([t for s, t in times if s == "GENERATE_NEW_SECRET"])
avg_time_agent = mean([t for s, t in times if s == "AGENT_PUSH"])
```

### Logs to Monitor

```sql
-- Sql query to find failures
SELECT * FROM audit_events 
WHERE event_type = 'credential_rotation_failed' 
AND timestamp > NOW() - INTERVAL 1 HOUR;

-- Find escalations
SELECT * FROM audit_events 
WHERE event_type = 'credential_rotation_failed' 
AND escalated_to_risk = true;

-- Find frozen accounts
SELECT * FROM audit_events 
WHERE event_type = 'credential_rotation_failed' 
AND account_frozen = true;
```

---

## References

- [Completion Report](STEP_19_COMPLETION_REPORT.md)
- [Quick Reference](STEP_19_QUICK_REFERENCE.md)
- [Strategy API](modules/credentials/rotation/strategy.py)
- [Test Suite](tests/test_step_19_rotation_strategies.py)

---

## Summary

**Step 19 Integration provides:**

✅ Drop-in replacement for RotationExecutor  
✅ Plugin-based strategy system  
✅ Three built-in strategies  
✅ Custom strategy support  
✅ Full audit integration  
✅ Security layer integration  
✅ Agent orchestration support  
✅ Zero-downtime strategy updates  

**Ready for immediate integration with CredentialModule**

