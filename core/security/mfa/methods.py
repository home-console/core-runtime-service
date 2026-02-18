"""
MFA Method Abstraction — supports TOTP now, WebAuthn/Passkey in future.

Architecture:
- Abstract base class MFAMethod for all auth methods
- Concrete TOTPMethod implementation (RFC 6238)
- Future: WebAuthnMethod, PasskeyMethod inherit from same base
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from dataclasses import dataclass

from core.security.mfa.totp import verify_totp
from core.security.mfa.exceptions import MFAFailed, MFANotConfigured


@dataclass(frozen=True)
class MFAVerificationResult:
    """Result of MFA verification attempt."""
    
    success: bool
    method_used: str
    user_id: str
    reason: Optional[str] = None  # On failure


class MFAMethod(ABC):
    """
    Abstract base for MFA methods.
    
    Each method:
    - Stores user secret in vault (not memory)
    - Verifies proof (code, assertion, signature, etc.)
    - Returns success/failure without raising exceptions
    
    Design allows easy addition of:
    - WebAuthn (FIDO2)
    - Passkeys (platform authenticators)
    - Hardware tokens (U2F)
    - SMS/Email OTP
    """
    
    @property
    @abstractmethod
    def method_name(self) -> str:
        """Unique method identifier (e.g., 'totp', 'webauthn')."""
        pass
    
    @abstractmethod
    async def is_configured(self, user_id: str, secret_store) -> bool:
        """Check if user has MFA configured for this method."""
        pass
    
    @abstractmethod
    async def verify(
        self,
        user_id: str,
        proof: Dict[str, Any],
        secret_store,
    ) -> MFAVerificationResult:
        """
        Verify proof (code, assertion, etc.).
        
        Args:
            user_id: User identifier
            proof: Method-specific proof (e.g., {"code": "123456"} for TOTP)
            secret_store: SecretStore instance for retrieving user secret
        
        Returns:
            MFAVerificationResult (always returns, never raises)
        """
        pass


class TOTPMethod(MFAMethod):
    """
    TOTP-based MFA (RFC 6238).
    
    User secret stored in vault as base32-encoded string.
    Namespace: mfa.secrets
    Key: user_id
    Value: {"secret": "JBSWY3DPEBLW64TMMQ======", "method": "totp"}
    """
    
    NAMESPACE = "mfa.secrets"
    
    @property
    def method_name(self) -> str:
        return "totp"
    
    async def is_configured(self, user_id: str, secret_store) -> bool:
        """Check if user has TOTP secret configured."""
        try:
            data = await secret_store.get(self.NAMESPACE, user_id)
            return data is not None and data.get("method") == "totp"
        except Exception:
            return False
    
    async def verify(
        self,
        user_id: str,
        proof: Dict[str, Any],
        secret_store,
    ) -> MFAVerificationResult:
        """
        Verify TOTP code.
        
        Proof format:
            {
                "code": "123456"  # 6-digit code from authenticator
            }
        """
        code = proof.get("code")
        
        if not code:
            return MFAVerificationResult(
                success=False,
                method_used=self.method_name,
                user_id=user_id,
                reason="missing_code",
            )
        
        if not isinstance(code, str) or len(code) != 6 or not code.isdigit():
            return MFAVerificationResult(
                success=False,
                method_used=self.method_name,
                user_id=user_id,
                reason="invalid_code_format",
            )
        
        # Retrieve TOTP secret from vault
        try:
            data = await secret_store.get(self.NAMESPACE, user_id)
            if not data:
                return MFAVerificationResult(
                    success=False,
                    method_used=self.method_name,
                    user_id=user_id,
                    reason="totp_not_configured",
                )
            
            secret = data.get("secret")
            if not secret:
                return MFAVerificationResult(
                    success=False,
                    method_used=self.method_name,
                    user_id=user_id,
                    reason="totp_secret_corrupted",
                )
        except Exception as e:
            return MFAVerificationResult(
                success=False,
                method_used=self.method_name,
                user_id=user_id,
                reason=f"vault_error: {str(e)}",
            )
        
        # Verify code with ±1 step window
        try:
            is_valid = verify_totp(secret, code, window=1)
            
            return MFAVerificationResult(
                success=is_valid,
                method_used=self.method_name,
                user_id=user_id,
                reason=None if is_valid else "invalid_code",
            )
        except Exception as e:
            return MFAVerificationResult(
                success=False,
                method_used=self.method_name,
                user_id=user_id,
                reason=f"verification_error: {str(e)}",
            )


# Future implementations (architecture ready)

class WebAuthnMethod(MFAMethod):
    """
    WebAuthn/FIDO2 MFA (future implementation).
    
    Will support:
    - Security keys (YubiKey, Titan)
    - Platform authenticators (Touch ID, Windows Hello)
    - Passkeys
    """
    
    @property
    def method_name(self) -> str:
        return "webauthn"
    
    async def is_configured(self, user_id: str, secret_store) -> bool:
        # TODO: implement
        return False
    
    async def verify(
        self,
        user_id: str,
        proof: Dict[str, Any],
        secret_store,
    ) -> MFAVerificationResult:
        # TODO: implement
        return MFAVerificationResult(
            success=False,
            method_used=self.method_name,
            user_id=user_id,
            reason="not_implemented",
        )


class PasskeyMethod(MFAMethod):
    """
    Passkey authentication (future implementation).
    
    Will support:
    - iCloud Keychain (Apple)
    - Bitwarden/1Password (cross-platform)
    """
    
    @property
    def method_name(self) -> str:
        return "passkey"
    
    async def is_configured(self, user_id: str, secret_store) -> bool:
        # TODO: implement
        return False
    
    async def verify(
        self,
        user_id: str,
        proof: Dict[str, Any],
        secret_store,
    ) -> MFAVerificationResult:
        # TODO: implement
        return MFAVerificationResult(
            success=False,
            method_used=self.method_name,
            user_id=user_id,
            reason="not_implemented",
        )
