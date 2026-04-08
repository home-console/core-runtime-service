"""
Operation context helpers — re-exported from core for plugin use.

Plugins should import from sdk, not from core directly.
"""

from core.runtime.operation_context import operation

__all__ = ["operation"]
