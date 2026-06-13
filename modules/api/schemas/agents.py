"""Agent DTO schemas."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class AgentDto(BaseModel):
    agent_id: str
    agent_name: str
    status: str
    version: Optional[str] = None
    last_seen: Optional[str] = None
    last_heartbeat: Optional[str] = None
    address: Optional[str] = None
    capabilities: Optional[List[str]] = None
    properties: Optional[Dict[str, Any]] = None


class DeploymentStatusDto(BaseModel):
    ok: bool = True
    deployment_id: Optional[str] = None
    agent_name: Optional[str] = None
    host: Optional[str] = None
    status: Optional[str] = None
    progress: Optional[int] = None
    agent_id: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    error: Optional[str] = None


class DeploymentSummaryDto(BaseModel):
    deployment_id: str
    agent_name: str
    host: str
    status: str
    created_at: str
    duration: Optional[float] = None
    error: Optional[str] = None


class DeploymentMetricsDto(BaseModel):
    ok: bool = True
    total: Optional[int] = None
    succeeded: Optional[int] = None
    failed: Optional[int] = None
    in_progress: Optional[int] = None
    success_rate: Optional[float] = None
    average_duration_seconds: Optional[float] = None
    by_status: Optional[Dict[str, int]] = None
    recent_5: Optional[List[DeploymentSummaryDto]] = None
    error: Optional[str] = None


class AgentHeartbeatDto(BaseModel):
    ok: bool = True
    agent_id: Optional[str] = None
    status: Optional[str] = None
    last_heartbeat: Optional[str] = None


class AgentHealthCheckDto(BaseModel):
    ok: bool = True
    error: Optional[str] = None
    timestamp: Optional[str] = None
    total_agents: Optional[int] = None
    stats: Optional[Dict[str, int]] = None
    total: Optional[int] = None
    online: Optional[int] = None
    offline: Optional[int] = None
    agents: Optional[List[Dict[str, Any]]] = None


class AgentLogEntryDto(BaseModel):
    timestamp: Optional[str] = None
    level: Optional[str] = None
    message: str
    context: Optional[Dict[str, Any]] = None


class AgentLogsDto(BaseModel):
    ok: bool = True
    agent_id: str
    logs: List[AgentLogEntryDto] = []
    total: int = 0
    agent_online: Optional[bool] = None


class AgentStatusDto(BaseModel):
    ok: bool = True
    error: Optional[str] = None
    agent_id: Optional[str] = None
    name: Optional[str] = None
    status: Optional[str] = None
    version: Optional[str] = None
    address: Optional[str] = None
    last_heartbeat: Optional[str] = None
    heartbeat_age_seconds: Optional[int] = None
    uptime_seconds: Optional[float] = None
    cpu_percent: Optional[float] = None
    memory_mb: Optional[float] = None
    capabilities: Optional[List[str]] = None
    deployment_id: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class EnrollmentTokenDto(BaseModel):
    ok: bool = True
    agent_name: Optional[str] = None
    token: Optional[str] = None
    expires_at: Optional[str] = None
    error: Optional[str] = None


class ChecksumDto(BaseModel):
    ok: bool = True
    error: Optional[str] = None
    message: Optional[str] = None
    sha256: Optional[str] = None
    size_bytes: Optional[int] = None
    filename: Optional[str] = None
    version: Optional[str] = None
    cached: Optional[bool] = None
    checksum: Optional[str] = None
    algorithm: Optional[str] = None


# --- Request models ---


class CreateEnrollmentTokenRequest(BaseModel):
    agent_name: str


class BootstrapTokenRequest(BaseModel):
    agent_name: str


class EnrollAgentRequest(BaseModel):
    agent_name: str
    token: str
    address: Optional[str] = None
    capabilities: Optional[List[str]] = None
    properties: Optional[Dict[str, Any]] = None


class DeployAgentRequest(BaseModel):
    agent_name: str
    credential_id: str
    core_url: Optional[str] = None


class HeartbeatRequest(BaseModel):
    status: Optional[str] = None
    version: Optional[str] = None
    capabilities: Optional[List[str]] = None
    properties: Optional[Dict[str, Any]] = None


class SubmitLogsRequest(BaseModel):
    logs: List[Dict[str, Any]] = []


class StartTerminalRequest(BaseModel):
    cols: Optional[int] = None
    rows: Optional[int] = None
    command: Optional[str] = None
