"""
Узкие группы исключений для D1 (диагностика без broad-catch).

Использование: ``except PLUGIN_INTROSPECTION_ERRORS as e:`` и т.п.
"""

from __future__ import annotations

# Реестр плагинов / metadata / get_loaded_plugins
PLUGIN_INTROSPECTION_ERRORS: tuple[type[BaseException], ...] = (
    AttributeError,
    KeyError,
    RuntimeError,
    TypeError,
    ValueError,
)

LOGGING_HELPER_ERRORS: tuple[type[BaseException], ...] = (
    AttributeError,
    KeyError,
    RuntimeError,
    TypeError,
    ValueError,
)

BEST_EFFORT_BACKGROUND_ERRORS: tuple[type[BaseException], ...] = (
    AttributeError,
    KeyError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
)

__all__ = [
    "BEST_EFFORT_BACKGROUND_ERRORS",
    "LOGGING_HELPER_ERRORS",
    "PLUGIN_INTROSPECTION_ERRORS",
]
