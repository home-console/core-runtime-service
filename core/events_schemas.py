"""
Схемы payload для событий event_bus.

Цель: единая документация контрактов publisher/subscriber без изменения поведения.
Файл используется как reference point для типов (TypedDict) и для ревью изменений.
"""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict


class ExternalDeviceStateReportedPayload(TypedDict):
    external_id: str
    state: dict[str, Any]
    source: NotRequired[str]  # e.g. "ws"
    online: NotRequired[bool]


class ExternalDeviceDiscoveredPayload(TypedDict, total=False):
    # Canonical fields (used by devices/automation)
    external_id: str
    provider: str
    capabilities: dict[str, Any]

    # Common optional fields used by some integrations/plugins (e.g. network_scanner)
    ip_address: str
    hostname: str
    mac_address: str
    os_type: str
    open_ports: list[int]
    services: Any

    # Catch-all payload container for provider-specific data
    data: dict[str, Any]


class OperationReadyPayload(TypedDict, total=False):
    """Событие постановки операции в очередь worker; см. docs/event_contracts/operation_ready.md."""

    # EventBus injects stable event id for claim/dedup (see dedup_contract / ADR 001).
    id: str
    type: str
    operation_id: str
    operation_type: str
    created_at: float


class OperationExecutionStartedPayload(TypedDict, total=False):
    execution_id: str
    operation_id: str
    operation_type: str
    started_at: float


class OperationExecutionCompletedPayload(TypedDict, total=False):
    execution_id: str
    operation_id: str
    operation_type: str
    status: str  # "ok" / "error"
    completed_at: float
    error: Any


class ExecutionScheduledPayload(TypedDict, total=False):
    schedule_id: str
    operation_type: str


class ExecutionStartedPayload(TypedDict, total=False):
    execution_id: str
    operation_id: str
    backend: str
    status: str


class ExecutionFinishedPayload(TypedDict, total=False):
    execution_id: str
    operation_id: str
    backend: str
    status: str


class PresenceEnteredPayload(TypedDict):
    old_state: bool
    new_state: bool


class PresenceLeftPayload(TypedDict):
    old_state: bool
    new_state: bool


# ============================================================================
# Client Manager plugin events (plugins/client-manager-plugin)
# ============================================================================

class ClientConnectedPayload(TypedDict, total=False):
    client_id: str
    metadata: dict[str, Any]
    source: NotRequired[str]  # "client_manager"


class ClientDisconnectedPayload(TypedDict, total=False):
    client_id: str
    client_info: Any
    source: NotRequired[str]


class ClientHeartbeatPayload(TypedDict, total=False):
    client_id: str
    source: NotRequired[str]


class CommandStartedPayload(TypedDict, total=False):
    command_id: str
    client_id: str
    command: str
    source: NotRequired[str]


class CommandCompletedPayload(TypedDict, total=False):
    command_id: str
    client_id: str
    command: str
    result: Any
    source: NotRequired[str]


class CommandFailedPayload(TypedDict, total=False):
    command_id: str
    client_id: str
    command: str
    error: str
    source: NotRequired[str]


class FileUploadStartedPayload(TypedDict, total=False):
    file_id: str
    client_id: str
    file_path: str
    size: int
    source: NotRequired[str]


class FileUploadCompletedPayload(TypedDict, total=False):
    file_id: str
    client_id: str
    file_path: str
    size: int
    result: Any
    source: NotRequired[str]


class FileUploadFailedPayload(TypedDict, total=False):
    file_id: str
    client_id: str
    file_path: str
    error: str
    source: NotRequired[str]


class FileDownloadStartedPayload(TypedDict, total=False):
    file_id: str
    client_id: str
    file_path: str
    source: NotRequired[str]


class FileDownloadCompletedPayload(TypedDict, total=False):
    file_id: str
    client_id: str
    file_path: str
    size: int
    source: NotRequired[str]


class FileDownloadFailedPayload(TypedDict, total=False):
    file_id: str
    client_id: str
    file_path: str
    error: str
    source: NotRequired[str]

