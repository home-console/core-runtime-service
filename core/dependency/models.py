"""
Dependency Resolution Models — error and exception types (D2).

Error definitions for dependency validation.
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any, List


@dataclass
class DependencyError:
    """Single dependency validation error."""
    code: str  # e.g., "missing_capability", "required_provider_removal"
    plugin: str  # plugin name that has the error
    message: str
    details: Optional[Dict[str, Any]] = None


class RuntimeIntegrityError(Exception):
    """Runtime has broken dependency graph."""
    
    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__(
            f"Runtime integrity check failed with {len(errors)} errors:\n" +
            "\n".join(f"  - {e}" for e in errors)
        )
