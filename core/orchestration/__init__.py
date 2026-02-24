"""
Orchestration Service — управление инфраструктурой плагинов.

REFACTORING: Проблема 8 - выделяем orchestration из AdminModule в отдельный слой.

Orchestration Service отвечает за:
- Управление жизненным циклом контейнеров плагинов
- Сборку и деплой образов
- Абстракцию над Docker/k8s/другими backend'ами
"""

from .service import OrchestrationService, get_orchestration_service, set_orchestration_service
from .docker_backend import DockerOrchestrationBackend

__all__ = [
    "OrchestrationService",
    "get_orchestration_service",
    "set_orchestration_service",
    "DockerOrchestrationBackend",
]
