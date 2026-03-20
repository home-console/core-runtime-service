"""Top-level modules package.

This package intentionally stays lightweight to avoid import cycles. Import concrete
subpackages directly, or access selected legacy module classes via lazy attributes.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = ["DevicesModule", "AutomationModule", "PresenceModule", "LoggerModule", "ApiModule", "AdminModule"]

_LAZY_EXPORTS = {
    "DevicesModule": ("modules.devices", "DevicesModule"),
    "AutomationModule": ("modules.automation", "AutomationModule"),
    "PresenceModule": ("modules.presence", "PresenceModule"),
    "LoggerModule": ("modules.logger", "LoggerModule"),
    "ApiModule": ("modules.api", "ApiModule"),
    "AdminModule": ("modules.admin", "AdminModule"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    module = import_module(module_name)
    return getattr(module, attribute_name)
