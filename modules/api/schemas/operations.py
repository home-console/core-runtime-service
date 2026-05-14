"""Operation and execution DTO schemas."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class OperationDto(BaseModel):
    operation_id: str
    type: Optional[str] = None
    status: str
    params: Optional[Dict[str, Any]] = None
    result: Optional[Any] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None


class ExecutionDto(BaseModel):
    execution_id: str
    operation_id: str
    operation_type: str
    backend: Optional[str] = None
    status: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    cancelled_at: Optional[str] = None
    duration_ms: Optional[float] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    stderr_tail: Optional[str] = None
    parent_execution_id: Optional[str] = None
    retry_index: Optional[int] = None


class ExecutionAttemptDto(BaseModel):
    execution_id: str
    retry_index: int
    status: str
    backend: Optional[str] = None
    parent_execution_id: Optional[str] = None
    children: Optional[List["ExecutionAttemptDto"]] = None


ExecutionAttemptDto.model_rebuild()


class ScheduleTriggerDto(BaseModel):
    type: str
    at: Optional[str] = None
    every_seconds: Optional[float] = None
    cron: Optional[str] = None
    timezone: Optional[str] = None


class ExecutionScheduleDto(BaseModel):
    schedule_id: str
    operation_type: str
    params: Optional[Dict[str, Any]] = None
    context: Optional[Dict[str, Any]] = None
    trigger: ScheduleTriggerDto
    enabled: bool
    max_runs: Optional[int] = None
    run_count: int = 0
    last_run_at: Optional[str] = None
    next_run_at: Optional[str] = None
    created_at: Optional[str] = None


class CreateOperationRequest(BaseModel):
    type: str
    params: Optional[Dict[str, Any]] = None
    context: Optional[Dict[str, Any]] = None


class CreateOperationResponse(BaseModel):
    ok: bool = True
    operation_id: Optional[str] = None
    status: Optional[str] = None
    error: Optional[str] = None


class CancelRetryResponse(BaseModel):
    ok: bool = True
    operation_id: Optional[str] = None
    error: Optional[str] = None
