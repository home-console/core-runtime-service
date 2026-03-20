"""
Core error types - backward compatibility re-export.

All errors are now in core.exceptions.errors
This module kept for backward compatibility with existing imports.
"""

from core.exceptions.errors import (
    CoreError,
    BadRequestError,
    UnauthorizedError,
    ForbiddenError,
    NotFoundError,
)

__all__ = [
    "CoreError",
    "BadRequestError",
    "UnauthorizedError",
    "ForbiddenError",
    "NotFoundError",
]
