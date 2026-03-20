"""
Module Manager Package (D2).

Runtime built-in modules management:
- manager.py: ModuleManager main class
- models.py: ModuleSpec dataclass

For backward compatibility, ModuleManager is re-exported from this package.
"""

from core.module.manager import ModuleManager
from core.module.models import ModuleSpec

__all__ = ["ModuleManager", "ModuleSpec"]
