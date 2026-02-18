"""Rotation engine exceptions."""


class RotationException(Exception):
    """Base exception for rotation operations."""
    pass


class RotationFailedError(RotationException):
    """Raised when rotation execution fails."""
    pass


class RotationNotAllowedError(RotationException):
    """Raised when rotation cannot proceed (e.g., account frozen)."""
    pass


class RotationTimeoutError(RotationException):
    """Raised when rotation takes too long."""
    pass


class RotationCancelledError(RotationException):
    """Raised when rotation is cancelled mid-execution."""
    pass


class SecretGenerationError(RotationException):
    """Raised when secret generation fails."""
    pass
