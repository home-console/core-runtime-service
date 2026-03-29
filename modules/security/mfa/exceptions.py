"""
MFA-related exceptions for elevated secret access.

All exceptions include context for audit logging.
"""


class MFAException(Exception):
    """Base exception for MFA operations."""
    pass


class MFARequired(MFAException):
    """
    Access requires MFA elevation but user has no active session.
    
    This is NOT an error — it's a challenge. User should retry with MFA code.
    """
    
    def __init__(
        self,
        user_id: str,
        credential_id: str,
        mfa_method: str = "totp",
    ):
        self.user_id = user_id
        self.credential_id = credential_id
        self.mfa_method = mfa_method
        
        super().__init__(
            f"MFA required for user {user_id} to access {credential_id}; "
            f"method={mfa_method}"
        )


class MFAFailed(MFAException):
    """MFA code verification failed or MFA method not configured."""
    
    def __init__(
        self,
        user_id: str,
        reason: str,
        mfa_method: str = "totp",
    ):
        self.user_id = user_id
        self.reason = reason
        self.mfa_method = mfa_method
        
        super().__init__(
            f"MFA verification failed for user {user_id}: {reason}"
        )


class MFANotConfigured(MFAException):
    """User has no MFA configuration (secret not registered)."""
    
    def __init__(self, user_id: str):
        self.user_id = user_id
        
        super().__init__(
            f"User {user_id} has no MFA configured"
        )


class ElevationSessionExpired(MFAException):
    """
    User has elevation session but it expired.
    
    User should re-authenticate with MFA.
    """
    
    def __init__(self, user_id: str, elevation_level: str):
        self.user_id = user_id
        self.elevation_level = elevation_level
        
        super().__init__(
            f"Elevation session expired for user {user_id} (level={elevation_level})"
        )


class ElevationSessionInvalid(MFAException):
    """Elevation session exists but is not valid for requested operation."""
    
    def __init__(
        self,
        user_id: str,
        required_level: str,
        session_level: str,
    ):
        self.user_id = user_id
        self.required_level = required_level
        self.session_level = session_level
        
        super().__init__(
            f"Elevation session invalid for user {user_id}: "
            f"required={required_level}, session={session_level}"
        )


class MFAMethodNotSupported(MFAException):
    """Requested MFA method is not supported."""
    
    def __init__(self, method_name: str):
        self.method_name = method_name
        
        super().__init__(
            f"MFA method not supported: {method_name}"
        )


class RateLimitExceeded(MFAException):
    """Too many failed MFA attempts. User locked temporarily."""
    
    def __init__(self, user_id: str, lockout_seconds: int):
        self.user_id = user_id
        self.lockout_seconds = lockout_seconds
        
        super().__init__(
            f"User {user_id} locked due to failed MFA attempts for {lockout_seconds}s"
        )
