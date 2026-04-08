"""
Deployment Tracker — отслеживает жизненный цикл развертывания агентов.

Отслеживает: PENDING → UPLOADING → DEPLOYING → REGISTERING → READY/FAILED
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Dict, List, Optional
import logging
logger = logging.getLogger(__name__)


class DeploymentStatus(str, Enum):
    """Deployment lifecycle states."""

    PENDING = "pending"
    UPLOADING = "uploading"
    DEPLOYING = "deploying"
    DEPLOYED = "deployed"
    REGISTERING = "registering"
    READY = "ready"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class DeploymentInfo:
    """Deployment lifecycle information."""

    deployment_id: str
    agent_name: str
    credential_id: str
    host: str
    status: DeploymentStatus = DeploymentStatus.PENDING
    progress_percentage: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    agent_id: Optional[str] = None
    enrollment_token_id: Optional[str] = None
    enrollment_token_str: Optional[str] = None
    custom_env: Dict[str, str] = field(default_factory=dict)
    install_stdout: Optional[str] = None
    install_stderr: Optional[str] = None

    def duration_seconds(self) -> Optional[float]:
        if self.completed_at:
            return (self.completed_at - self.created_at).total_seconds()
        return None

    def to_dict(self) -> Dict:
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        if self.started_at:
            data["started_at"] = self.started_at.isoformat()
        if self.completed_at:
            data["completed_at"] = self.completed_at.isoformat()
        data["status"] = self.status.value
        data.pop("enrollment_token_str", None)
        return data


class DeploymentTracker:
    """In-memory deployment tracker with optional DB persistence."""

    def __init__(self, db_service=None):
        self._in_memory: Dict[str, DeploymentInfo] = {}
        self._sorted_cache: List[DeploymentInfo] = []
        self._cache_dirty = True
        self._db = db_service
        self._lock_on_disk = False

    async def create(
        self,
        deployment_id: str,
        agent_name: str,
        credential_id: str,
        host: str,
        custom_env: Optional[Dict[str, str]] = None,
    ) -> DeploymentInfo:
        deployment = DeploymentInfo(
            deployment_id=deployment_id,
            agent_name=agent_name,
            credential_id=credential_id,
            host=host,
            custom_env=custom_env or {},
        )

        self._in_memory[deployment_id] = deployment
        self._cache_dirty = True

        if self._db:
            try:
                await self._db.insert("deployments", deployment.to_dict())
            except Exception:
                logger.warning("Unhandled exception", exc_info=True)

        return deployment

    async def get(self, deployment_id: str) -> Optional[DeploymentInfo]:
        return self._in_memory.get(deployment_id)

    async def update_status(
        self,
        deployment_id: str,
        status: str,
        progress: Optional[int] = None,
        agent_id: Optional[str] = None,
        error_message: Optional[str] = None,
        completed_at: Optional[str] = None,
        install_stdout: Optional[str] = None,
        install_stderr: Optional[str] = None,
        **kwargs,
    ) -> bool:
        deployment = self._in_memory.get(deployment_id)

        if not deployment:
            return False

        try:
            new_status = DeploymentStatus(status)
        except ValueError:
            return False

        deployment.status = new_status

        if progress is not None:
            deployment.progress_percentage = min(100, max(0, progress))
        if agent_id:
            deployment.agent_id = agent_id
        if error_message:
            deployment.error_message = error_message
        if install_stdout is not None:
            deployment.install_stdout = install_stdout
        if install_stderr is not None:
            deployment.install_stderr = install_stderr
        if completed_at:
            try:
                deployment.completed_at = datetime.fromisoformat(completed_at)
            except ValueError:
                pass

        self._cache_dirty = True

        if deployment.status in [
            DeploymentStatus.READY,
            DeploymentStatus.FAILED,
            DeploymentStatus.TIMEOUT,
        ]:
            if not deployment.completed_at:
                deployment.completed_at = datetime.now(timezone.utc)

        if deployment.status != DeploymentStatus.PENDING and not deployment.started_at:
            deployment.started_at = datetime.now(timezone.utc)

        if self._db:
            try:
                await self._db.update(
                    "deployments",
                    {"deployment_id": deployment_id},
                    deployment.to_dict(),
                )
            except Exception:
                logger.warning("Unhandled exception", exc_info=True)

        return True

    async def list_deployments(
        self,
        agent_name: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[DeploymentInfo]:
        if self._cache_dirty:
            self._sorted_cache = sorted(
                self._in_memory.values(), key=lambda d: d.created_at, reverse=True
            )
            self._cache_dirty = False

        results = self._sorted_cache

        if agent_name:
            results = [d for d in results if d.agent_name == agent_name]

        if status:
            results = [d for d in results if d.status.value == status]

        return results[:limit]

    async def cleanup_old_deployments(self, older_than_hours: int = 24):
        deadline = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)

        to_delete = [
            deployment_id
            for deployment_id, deployment in self._in_memory.items()
            if deployment.completed_at and deployment.completed_at < deadline
        ]

        for deployment_id in to_delete:
            del self._in_memory[deployment_id]

        if to_delete:
            self._cache_dirty = True

        return len(to_delete)

    async def get_deployment_metrics(self) -> Dict:
        all_deployments = await self.list_deployments(limit=1000)

        if not all_deployments:
            return {
                "total": 0,
                "succeeded": 0,
                "failed": 0,
                "in_progress": 0,
                "average_duration_seconds": 0,
                "by_status": {},
                "recent_5": [],
            }

        succeeded = [d for d in all_deployments if d.status == DeploymentStatus.READY]
        failed = [
            d
            for d in all_deployments
            if d.status in [DeploymentStatus.FAILED, DeploymentStatus.TIMEOUT]
        ]
        in_progress = [
            d
            for d in all_deployments
            if d.status
            not in [
                DeploymentStatus.READY,
                DeploymentStatus.FAILED,
                DeploymentStatus.TIMEOUT,
            ]
        ]

        durations = [
            duration
            for duration in (d.duration_seconds() for d in all_deployments)
            if duration is not None
        ]
        avg_duration = sum(durations) / len(durations) if durations else 0

        return {
            "total": len(all_deployments),
            "succeeded": len(succeeded),
            "failed": len(failed),
            "in_progress": len(in_progress),
            "success_rate": len(succeeded) / len(all_deployments)
            if all_deployments
            else 0,
            "average_duration_seconds": avg_duration,
            "by_status": {
                status: len([d for d in all_deployments if d.status == status])
                for status in DeploymentStatus
            },
            "recent_5": [
                {
                    "deployment_id": d.deployment_id,
                    "agent_name": d.agent_name,
                    "host": d.host,
                    "status": d.status.value,
                    "created_at": d.created_at.isoformat(),
                    "duration": d.duration_seconds(),
                    "error": d.error_message,
                }
                for d in all_deployments[:5]
            ],
        }
