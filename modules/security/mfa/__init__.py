"""
MFA Module — Multi-Factor Authentication for zero-trust secret access.

Components:
- exceptions: MFA-specific exceptions
- totp: RFC 6238 TOTP implementation
- methods: Abstract MFA method interface + implementations
- elevation_session: In-memory session manager with TTL
- service: MFAService orchestration
"""

from modules.security.mfa.exceptions import (
    MFARequired,
    MFAFailed,
    MFANotConfigured,
    ElevationSessionExpired,
    ElevationSessionInvalid,
    MFAMethodNotSupported,
    RateLimitExceeded,
)
from modules.security.mfa.totp import (
    generate_totp,
    verify_totp,
)
from modules.security.mfa.methods import (
    MFAMethod,
    MFAVerificationResult,
    TOTPMethod,
    WebAuthnMethod,
    PasskeyMethod,
)
from modules.security.mfa.elevation_session import (
    ElevationSession,
    ElevationSessionManager,
)
from modules.security.mfa.service import MFAService

__all__ = [
    # Exceptions
    "MFARequired",
    "MFAFailed",
    "MFANotConfigured",
    "ElevationSessionExpired",
    "ElevationSessionInvalid",
    "MFAMethodNotSupported",
    "RateLimitExceeded",
    
    # TOTP
    "generate_totp",
    "verify_totp",
    
    # Methods
    "MFAMethod",
    "MFAVerificationResult",
    "TOTPMethod",
    "WebAuthnMethod",
    "PasskeyMethod",
    
    # Session Management
    "ElevationSession",
    "ElevationSessionManager",
    
    # Service
    "MFAService",
]
