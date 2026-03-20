"""
Backwards-compatible shim for `core.runtime_context`.

Re-exports `RuntimeContext` and `LegacyRuntimeContext` from
`core.runtime.runtime_context` to satisfy imports that expect the
top-level module.
"""

from core.runtime.runtime_context import RuntimeContext, LegacyRuntimeContext

__all__ = ["RuntimeContext", "LegacyRuntimeContext"]
