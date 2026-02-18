"""Main credential rotation engine."""

from datetime import datetime, timezone
from typing import Optional, Dict, Any
import asyncio

from .policy import RotationPolicy, RotationState, RotationStatus
from .scheduler import RotationScheduler
from .executor import RotationExecutor
from .exceptions import (
    RotationFailedError,
    RotationNotAllowedError,
)


class CredentialRotationEngine:
    """
    Main credential rotation engine.
    
    Orchestrates:
    - Scheduling rotations (when)
    - Executing rotations (how)
    - Tracking state (status)
    - Logging events (audit)
    
    Entry point for all rotation operations.
    """
    
    def __init__(
        self,
        vault_store: Any,
        repository: Any,
        audit_binder: Any,
        security_orchestrator: Optional[Any] = None,
        trust_engine: Optional[Any] = None,
        check_interval_seconds: int = 60,
    ):
        """
        Initialize rotation engine.
        
        Args:
            vault_store: Secret storage (SecretStore)
            repository: Credential metadata storage
            audit_binder: Audit event logging
            security_orchestrator: Security checks
            trust_engine: Trust state checks
            check_interval_seconds: How often to check for due rotations
        """
        self.vault_store = vault_store
        self.repository = repository
        self.audit_binder = audit_binder
        self.security_orchestrator = security_orchestrator
        self.trust_engine = trust_engine
        
        self.scheduler = RotationScheduler(check_interval_seconds)
        self.executor = RotationExecutor(
            vault_store=vault_store,
            repository=repository,
            audit_binder=audit_binder,
            security_orchestrator=security_orchestrator,
            trust_engine=trust_engine,
        )
        
        self._running = False
        self._work_task: Optional[asyncio.Task] = None
        self._rotation_policies: Dict[str, RotationPolicy] = {}
    
    async def start(self) -> None:
        """Start rotation engine background tasks."""
        if self._running:
            return
        
        self._running = True
        await self.scheduler.start()
        
        # Start worker task
        self._work_task = asyncio.create_task(self._process_due_rotations())
        
        await self.audit_binder.append_event(
            event_type="rotation_engine_started",
            metadata={"timestamp": datetime.now(timezone.utc).isoformat()}
        )
    
    async def stop(self) -> None:
        """Stop rotation engine."""
        self._running = False
        await self.scheduler.stop()
        
        if self._work_task:
            self._work_task.cancel()
            try:
                await self._work_task
            except asyncio.CancelledError:
                pass
        
        await self.audit_binder.append_event(
            event_type="rotation_engine_stopped",
            metadata={"timestamp": datetime.now(timezone.utc).isoformat()}
        )
    
    async def schedule_rotation(
        self,
        credential_id: str,
        rotation_policy: RotationPolicy,
        last_rotated_at: Optional[str] = None,
    ) -> None:
        """
        Schedule a credential for rotation.
        
        Args:
            credential_id: ID of credential
            rotation_policy: When/how to rotate
            last_rotated_at: Previous rotation time (optional)
        
        Raises:
            ValueError: if validation fails
        """
        # Validate policy
        rotation_policy.validate()
        
        # Store policy
        self._rotation_policies[credential_id] = rotation_policy
        
        # Schedule in scheduler
        await self.scheduler.schedule(
            credential_id=credential_id,
            rotation_policy=rotation_policy,
            last_rotated_at=last_rotated_at,
        )
        
        # Log event
        await self.audit_binder.append_event(
            event_type="credential_rotation_scheduled",
            resource_id=credential_id,
            metadata={
                "credential_id": credential_id,
                "interval_seconds": rotation_policy.interval_seconds,
                "strategy": rotation_policy.strategy.value,
                "auto_rotate": rotation_policy.auto_rotate,
            }
        )
    
    async def rotate_now(
        self,
        credential_id: str,
        rotation_policy: Optional[RotationPolicy] = None,
    ) -> None:
        """
        Manually trigger rotation immediately.
        
        Args:
            credential_id: ID of credential to rotate
            rotation_policy: Override policy (optional)
        
        Raises:
            RotationFailedError: if rotation fails
            RotationNotAllowedError: if rotation cannot proceed
        """
        # Use provided policy or retrieve stored policy
        policy = rotation_policy or self._rotation_policies.get(credential_id)
        if not policy:
            raise ValueError(f"No rotation policy for {credential_id}")
        
        # Mark as in-progress
        await self.scheduler.mark_rotation_started(credential_id)
        
        try:
            # Get current credential
            credential = await self.repository.get(credential_id)
            if not credential:
                raise RotationFailedError(f"Credential not found: {credential_id}")
            
            # Execute rotation
            new_secret_ref, new_version = await self.executor.execute_rotation(
                credential_id=credential_id,
                rotation_policy=policy,
                current_version=credential.version,
            )
            
            # Update credential (increment version)
            updated = credential.mutate(
                secret_ref=new_secret_ref,
            )
            await self.repository.update(updated)
            
            # Mark completed
            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            await self.scheduler.mark_rotation_completed(
                credential_id=credential_id,
                new_last_rotated_at=now,
                rotation_policy=policy,
            )
            
            await self.audit_binder.append_event(
                event_type="credential_rotation_complete",
                resource_id=credential_id,
                metadata={
                    "credential_id": credential_id,
                    "new_version": new_version,
                    "success": True,
                }
            )
            
        except (RotationFailedError, RotationNotAllowedError) as e:
            # Check if too many failures
            policy = self._rotation_policies.get(credential_id)
            if policy:
                failed = await self.scheduler.mark_rotation_failed(
                    credential_id=credential_id,
                    error_reason=str(e),
                    max_failures=policy.max_failures,
                )
                
                if failed:
                    # Trigger account freeze on repeated failures
                    if self.trust_engine:
                        await self.trust_engine.freeze(
                            user_id=credential_id,
                            reason="Credential rotation repeated failures",
                        )
            
            raise
    
    async def check_due_rotations(self) -> list[str]:
        """
        Check for rotations currently due.
        
        Returns:
            List of credential IDs that need rotation
        """
        return await self.scheduler.get_due_rotations()
    
    async def cancel_rotation(self, credential_id: str) -> None:
        """
        Cancel scheduled rotation for a credential.
        
        Args:
            credential_id: ID of credential
        """
        await self.scheduler.cancel_rotation(credential_id)
        
        await self.audit_binder.append_event(
            event_type="credential_rotation_cancelled",
            resource_id=credential_id,
            metadata={"credential_id": credential_id}
        )
    
    async def get_rotation_state(self, credential_id: str) -> Optional[RotationState]:
        """
        Get current rotation state for a credential.
        
        Args:
            credential_id: ID of credential
        
        Returns:
            RotationState or None if not scheduled
        """
        return await self.scheduler.get_state(credential_id)
    
    async def _process_due_rotations(self) -> None:
        """Background worker to process due rotations."""
        while self._running:
            try:
                # Check for due rotations
                due_ids = await self.scheduler.get_due_rotations()
                
                # Process each (with concurrency limit)
                tasks = []
                for cred_id in due_ids:
                    policy = self._rotation_policies.get(cred_id)
                    if policy and policy.auto_rotate:
                        tasks.append(self._rotate_one(cred_id, policy))
                
                if tasks:
                    # Process up to 5 in parallel
                    for i in range(0, len(tasks), 5):
                        batch = tasks[i:i+5]
                        await asyncio.gather(*batch, return_exceptions=True)
                
                await asyncio.sleep(10)  # Check every 10 seconds
                
            except asyncio.CancelledError:
                break
            except Exception:
                # Continue on errors
                await asyncio.sleep(10)
    
    async def _rotate_one(
        self,
        credential_id: str,
        policy: RotationPolicy,
    ) -> None:
        """Rotate a single credential (called by worker)."""
        try:
            await self.rotate_now(credential_id, policy)
        except Exception:
            # Error already logged by rotate_now
            pass
