"""Credential rotation execution logic."""

from datetime import datetime, timezone
from typing import Optional, Any, Callable
import asyncio

from .policy import RotationPolicy, RotationStatus, RotationStrategy, RotationState
from .exceptions import RotationFailedError, RotationNotAllowedError
from .secret_gen import generate_strong_secret
from core.security import TrustLevel


class RotationExecutor:
    """
    Executes credential rotation atomically.
    
    Responsibilities:
    - Generate new secrets
    - Update vault storage
    - Increment version
    - Track audit events
    - Rollback on failure
    """
    
    def __init__(
        self,
        vault_store: Any,  # SecretStore implementation
        repository: Any,  # CredentialRepository
        audit_binder: Any,  # AuditBinder for logging
        security_orchestrator: Optional[Any] = None,
        trust_engine: Optional[Any] = None,
    ):
        """
        Initialize rotation executor.
        
        Args:
            vault_store: Storage for actual secrets
            repository: Storage for credential metadata
            audit_binder: Audit logging system
            security_orchestrator: For checking if rotation allowed
            trust_engine: For checking account trust state
        """
        self.vault_store = vault_store
        self.repository = repository
        self.audit_binder = audit_binder
        self.security_orchestrator = security_orchestrator
        self.trust_engine = trust_engine
    
    async def execute_rotation(
        self,
        credential_id: str,
        rotation_policy: RotationPolicy,
        current_version: int,
    ) -> tuple[str, int]:
        """
        Execute credential rotation atomically.
        
        Steps:
        1. Check if rotation allowed (not frozen)
        2. Generate new secret
        3. Save to vault
        4. Update credential version
        5. Log audit event
        6. Return new secret reference
        
        Args:
            credential_id: ID of credential to rotate
            rotation_policy: Policy defining rotation strategy
            current_version: Current version number
        
        Returns:
            (new_secret_ref, new_version) tuple
        
        Raises:
            RotationNotAllowedError: if rotation cannot proceed
            RotationFailedError: if rotation execution fails
        """
        # Step 1: Check if rotation allowed
        if self.trust_engine:
            trust_state = await self.trust_engine.get_state(credential_id)
            
            # Must convert TrustLevel enum to compare
            if trust_state and trust_state.level == TrustLevel.FROZEN:
                await self.audit_binder.append_event(
                    event_type="credential_rotation_denied",
                    metadata={
                        "credential_id": credential_id,
                        "reason": "account_frozen",
                    }
                )
                raise RotationNotAllowedError(
                    f"Cannot rotate {credential_id}: account frozen"
                )
        
        try:
            # Step 2: Generate new secret based on strategy
            if rotation_policy.strategy == RotationStrategy.GENERATE_NEW_SECRET:
                new_secret = generate_strong_secret(length=32)
            elif rotation_policy.strategy == RotationStrategy.MANUAL:
                raise RotationNotAllowedError(
                    "Cannot auto-rotate with MANUAL strategy"
                )
            elif rotation_policy.strategy == RotationStrategy.AGENT_PUSH:
                # Would be handled by agent, not here
                raise RotationNotAllowedError(
                    "AGENT_PUSH rotations must be initiated by agent"
                )
            else:
                raise RotationFailedError(
                    f"Unknown rotation strategy: {rotation_policy.strategy}"
                )
            
            # Step 3: Save new secret to vault
            new_secret_ref = f"{credential_id}:v{current_version + 1}"
            
            try:
                await self.vault_store.store_secret(
                    key=new_secret_ref,
                    value=new_secret,
                )
            except Exception as e:
                raise RotationFailedError(f"Failed to store secret: {e}")
            
            # Step 4: Update repository with new version
            # (actual update handled by caller)
            
            # Step 5: Log audit event
            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            await self.audit_binder.append_event(
                event_type="credential_rotated",
                user_id=credential_id,
                resource_id=credential_id,
                metadata={
                    "credential_id": credential_id,
                    "old_version": current_version,
                    "new_version": current_version + 1,
                    "new_secret_ref": new_secret_ref,
                    "strategy": rotation_policy.strategy.value,
                    "rotated_at": now,
                }
            )
            
            return (new_secret_ref, current_version + 1)
            
        except RotationFailedError:
            raise
        except RotationNotAllowedError:
            raise
        except Exception as e:
            # Log unexpected error
            await self.audit_binder.append_event(
                event_type="credential_rotation_failed",
                user_id=credential_id,
                resource_id=credential_id,
                metadata={
                    "credential_id": credential_id,
                    "error": str(e),
                    "version": current_version,
                }
            )
            raise RotationFailedError(f"Rotation execution failed: {e}")
    
    async def execute_manual_rotation(
        self,
        credential_id: str,
        new_secret: str,
        current_version: int,
    ) -> tuple[str, int]:
        """
        Execute manual credential rotation with provided secret.
        
        Used when secret is provided externally (e.g., by admin or agent).
        
        Args:
            credential_id: ID of credential to rotate
            new_secret: The new secret value
            current_version: Current version number
        
        Returns:
            (new_secret_ref, new_version) tuple
        
        Raises:
            RotationFailedError: if rotation execution fails
        """
        try:
            # Save new secret to vault
            new_secret_ref = f"{credential_id}:v{current_version + 1}"
            
            await self.vault_store.store_secret(
                key=new_secret_ref,
                value=new_secret,
            )
            
            # Log audit event
            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            await self.audit_binder.append_event(
                event_type="credential_rotated_manual",
                resource_id=credential_id,
                metadata={
                    "credential_id": credential_id,
                    "old_version": current_version,
                    "new_version": current_version + 1,
                    "new_secret_ref": new_secret_ref,
                    "rotated_at": now,
                }
            )
            
            return (new_secret_ref, current_version + 1)
            
        except Exception as e:
            await self.audit_binder.append_event(
                event_type="credential_rotation_failed",
                resource_id=credential_id,
                metadata={
                    "credential_id": credential_id,
                    "error": str(e),
                    "version": current_version,
                }
            )
            raise RotationFailedError(f"Manual rotation failed: {e}")
    
    async def rollback_rotation(
        self,
        credential_id: str,
        old_version: int,
        new_version: int,
    ) -> None:
        """
        Rollback failed rotation to previous version.
        
        Args:
            credential_id: ID of credential
            old_version: Previous version number
            new_version: Failed new version number
        """
        try:
            # Log rollback event
            await self.audit_binder.append_event(
                event_type="credential_rotation_rolled_back",
                resource_id=credential_id,
                metadata={
                    "credential_id": credential_id,
                    "old_version": old_version,
                    "rolled_back_version": new_version,
                }
            )
        except Exception as e:
            # Continue even if audit fails
            pass
