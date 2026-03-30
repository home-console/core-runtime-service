"""
App-level orchestration service — вынесено из core для соблюдения границ ядра.

Orchestration — это инфраструктурная ответственность app-layer, не ядра.
Ядро принимает только контракт (порт), реализация создаётся в app.
"""

from app.orchestration.service import (
    OrchestrationBackend,
    OrchestrationService,
    NullOrchestrationBackend,
)
from app.orchestration.docker_backend import DockerOrchestrationBackend

__all__ = [
    "OrchestrationBackend",
    "OrchestrationService",
    "NullOrchestrationBackend",
    "DockerOrchestrationBackend",
]
