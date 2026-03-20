"""
Dependency Resolver Package (D2).

System-level integrity checking:
- resolver.py: DependencyResolver main class
- models.py: DependencyError and RuntimeIntegrityError exceptions

For backward compatibility, DependencyResolver is re-exported from this package.
"""

from core.dependency.resolver import DependencyResolver
from core.dependency.models import DependencyError, RuntimeIntegrityError

__all__ = ["DependencyResolver", "DependencyError", "RuntimeIntegrityError"]
