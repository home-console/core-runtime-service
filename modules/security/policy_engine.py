"""
Policy Engine for Credential Access Control

Evaluates access decisions based on roles, user ownership, and policies.
Pure evaluation logic - no side effects, no state mutation.
"""

from typing import Optional, Protocol
from datetime import datetime

from modules.security.rbac_models import (
    Role,
    CredentialAccessLevel,
    CredentialPolicy,
    AccessDecision,
)


class PolicyStore(Protocol):
    """Interface for policy storage."""
    
    async def get_policy(self, credential_id: str) -> Optional[CredentialPolicy]:
        """Get policy for credential."""
        ...


class CredentialPolicyEngine:
    """
    Pure policy evaluation engine.
    
    No direct side effects. All decisions logged externally via audit binding.
    Supports:
    - Owner-based access (owner can access own credentials)
    - Role-based access (specific roles allowed for operations)
    - User-specific access (explicit user allowlists)
    - Admin bypass (ADMIN role has all access)
    - Granular secret access (READ_SECRET requires elevated role)
    """
    
    def __init__(self, policy_store: PolicyStore):
        self.policy_store = policy_store
    
    async def evaluate(
        self,
        user_id: str,
        user_roles: list[Role],
        credential_id: str,
        access_level: CredentialAccessLevel,
    ) -> AccessDecision:
        """
        Evaluate access decision for user accessing credential.
        
        Returns AccessDecision with allowed=True/False and reason.
        
        Decision logic:
        1. ADMIN role -> ALLOW (bypass all checks)
        2. For READ_SECRET -> CHECK secret_read_roles FIRST (even owner must have elevated role)
        3. User owner + access_level != DELETE -> ALLOW (for non-secret operations)
        4. For role-based access -> CHECK allowed_roles
        5. Check allowed_users list
        6. Default -> DENY
        """
        
        policy = await self.policy_store.get_policy(credential_id)
        if policy is None:
            # No policy found - deny by default (secure fail)
            return AccessDecision(
                allowed=False,
                reason="No policy found for credential"
            )
        
        # Rule 1: ADMIN role bypass
        if Role.ADMIN in user_roles:
            return AccessDecision(
                allowed=True,
                reason="Admin user has universal access"
            )
        
        # Rule 2: Elevated secret access (check FIRST, even owner must have role)
        if access_level == CredentialAccessLevel.READ_SECRET:
            # Must have elevated role
            allowed_secret_roles = policy.secret_read_roles
            if not allowed_secret_roles:
                # No roles allowed to read secret -> deny
                return AccessDecision(
                    allowed=False,
                    reason="No roles allowed to read secrets for this credential",
                    required_roles=allowed_secret_roles
                )
            
            # Check if user has any of the required roles
            user_role_set = set(user_roles)
            allowed_role_set = set(allowed_secret_roles)
            if not user_role_set & allowed_role_set:
                return AccessDecision(
                    allowed=False,
                    reason=f"User roles {[r.value for r in user_roles]} not in secret_read_roles {[r.value for r in allowed_secret_roles]}",
                    required_roles=allowed_secret_roles
                )
            
            # User has required role for secret access
            return AccessDecision(
                allowed=True,
                reason=f"User has required role for secret read"
            )
        
        # Rule 3: Owner check (for non-secret operations)
        is_owner = user_id == policy.owner_user_id
        if is_owner:
            if access_level == CredentialAccessLevel.DELETE:
                return AccessDecision(
                    allowed=False,
                    reason="Only ADMIN can delete credentials"
                )
            # Owner can perform all non-delete, non-secret operations
            return AccessDecision(
                allowed=True,
                reason=f"User is credential owner"
            )
        
        # Rule 4: Role-based access for non-secret operations
        allowed_roles = policy.allowed_roles
        if allowed_roles:
            user_role_set = set(user_roles)
            allowed_role_set = set(allowed_roles)
            if user_role_set & allowed_role_set:
                return AccessDecision(
                    allowed=True,
                    reason=f"User role matches allowed_roles"
                )
        
        # Rule 5: User-specific access
        if user_id in policy.allowed_users:
            return AccessDecision(
                allowed=True,
                reason=f"User in allowed_users list"
            )
        
        # Rule 6: Default deny (secure default)
        return AccessDecision(
            allowed=False,
            reason=f"User {user_id} with roles {[r.value for r in user_roles]} not authorized for {access_level.value}"
        )
    
    async def is_allowed(
        self,
        user_id: str,
        user_roles: list[Role],
        credential_id: str,
        access_level: CredentialAccessLevel,
    ) -> bool:
        """
        Convenience method: returns bool True/False.
        """
        decision = await self.evaluate(user_id, user_roles, credential_id, access_level)
        return decision.allowed
