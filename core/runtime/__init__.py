"""Runtime package.

CoreRuntime is exposed lazily to avoid import cycles during package bootstrap.
"""

from importlib import import_module

__all__ = ["CoreRuntime", "StateEngine", "Config", "RuntimeModule"]


def __getattr__(name: str):
    if name == "CoreRuntime":
        return import_module("core.runtime.runtime").CoreRuntime
    if name == "StateEngine":
        return import_module("core.runtime.state_engine").StateEngine
    if name == "Config":
        return import_module("core.runtime.config").Config
    if name == "RuntimeModule":
        return import_module("core.runtime.runtime_module").RuntimeModule
    raise AttributeError(f"module 'core.runtime' has no attribute {name!r}")
