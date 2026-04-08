"""
Dependency Resolver Package.

System-level integrity checking and plugin lifecycle policy.

Primary components (new code should use these directly):
- integrity_checker.py: DependencyIntegrityChecker — runtime integrity validation
- lifecycle_policy.py: PluginLifecyclePolicy — plugin lifecycle decisions
"""

from core.dependency.integrity_checker import DependencyIntegrityChecker
from core.dependency.lifecycle_policy import PluginLifecyclePolicy
from core.dependency.models import DependencyError, RuntimeIntegrityError
from core.dependency.result import (
    Result,
    Ok,
    Err,
    Error,
    ok,
    err,
    from_exception,
    collect_errors,
    first_error,
    all_ok,
)

__all__ = [
    # Primary components
    "DependencyIntegrityChecker",
    "PluginLifecyclePolicy",
    # Exceptions
    "DependencyError",
    "RuntimeIntegrityError",
    # Result type
    "Result",
    "Ok",
    "Err",
    "Error",
    "ok",
    "err",
    "from_exception",
    "collect_errors",
    "first_error",
    "all_ok",
]
