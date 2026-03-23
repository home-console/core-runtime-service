"""
Core/Remote package - remote provider interfaces.
"""

from core.remote_executor_interface import IRemoteExecutor
from core.remote_provider import RemoteCapabilityProvider

__all__ = [
    "IRemoteExecutor",
    "RemoteCapabilityProvider",
]
