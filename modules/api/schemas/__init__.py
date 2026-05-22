"""
API DTO schemas — HTTP contract layer.

Rules:
  - No imports from core.* (pure Pydantic models)
  - All response models are wrapped in ApiResponse[T] via _normalize_api_result
  - All request models replace Dict[str, Any] body in bind_routes
"""
from .common import ApiResponse, DeletedResponse, OkErrorResponse, OkResponse
from .auth import (
    ApiKeyDto,
    AuthTokenDto,
    BootstrapStatusDto,
    ChangePasswordRequest,
    CreateApiKeyRequest,
    CreateUserRequest,
    DevCredentialsDto,
    InitializeRequest,
    LoginRequest,
    RevokeApiKeyRequest,
    RevokeSessionRequest,
    RotateApiKeyRequest,
    SessionDto,
    SetPasswordRequest,
    UserDto,
)
from .devices import (
    DeviceDto,
    DeviceMappingDto,
    DeviceStateDto,
    ExternalDeviceDto,
    SetDeviceStateRequest,
)
from .plugin import (
    AutoLoadRequest,
    EnsureContainerRequest,
    LoadPluginRequest,
    PluginDetailsDto,
    PluginDto,
    PluginsDiscoverDto,
)
from .plugin_ui import (
    DashboardCardDto,
    DashboardCardsListDto,
    PluginUiContributionsDto,
    UiPageContributionDto,
    UiWidgetContributionDto,
)
from .plugin_config import (
    PluginConfigDto,
    PluginServiceInvokeRequest,
    PluginServiceInvokeResult,
    SetPluginConfigRequest,
)
from .operations import (
    CancelRetryResponse,
    CreateOperationRequest,
    CreateOperationResponse,
    ExecutionAttemptDto,
    ExecutionDto,
    ExecutionScheduleDto,
    OperationDto,
)
from .inspector import (
    DashboardSummaryDto,
    HttpEndpointInfoDto,
    IntegrationFlowDto,
    InventorySnapshotDto,
    OperationTypeDto,
    RuntimeEventDto,
    RuntimeInfoDto,
    ServiceDto,
    SystemHealthDto,
    WsEndpointInfoDto,
)
from .agents import (
    AgentDto,
    AgentHealthCheckDto,
    AgentHeartbeatDto,
    AgentLogsDto,
    AgentStatusDto,
    BootstrapTokenRequest,
    ChecksumDto,
    CreateEnrollmentTokenRequest,
    DeployAgentRequest,
    DeploymentMetricsDto,
    DeploymentStatusDto,
    EnrollAgentRequest,
    EnrollmentTokenDto,
    HeartbeatRequest,
    StartTerminalRequest,
    SubmitLogsRequest,
)
from .credentials import (
    CreateCredentialRequest,
    CredentialDto,
    TerminalSessionStartDto,
    UpdateCredentialRequest,
)
from .ssh import CreateSshSessionRequest, SshSessionDto
from .storage import StorageNamespaceContentsDto, StorageNamespaceDto
from .marketplace import (
    BuildGitCatalogRequest,
    GitCatalogEntryDto,
    GitSourcesDto,
    InstallFromArchiveRequest,
    InstallFromGitRequest,
    InstallFromRegistryRequest,
    UpdateFromRegistryRequest,
    InstalledPluginDto,
    MarketplaceCatalogEntryDto,
    MarketplaceResultDto,
    RemovePluginRequest,
    SetGitSourcesRequest,
    UpdatePluginRequest,
)
from .integrations import IntegrationDto
from .presence import PresenceStatusDto
from .skills import SkillDto, SkillInvokeRequest, SkillInvokeResult, SkillListDto

__all__ = [
    # common
    "ApiResponse", "OkResponse", "OkErrorResponse", "DeletedResponse",
    # auth
    "UserDto", "SessionDto", "ApiKeyDto", "AuthTokenDto", "BootstrapStatusDto",
    "DevCredentialsDto",
    "LoginRequest", "InitializeRequest", "SetPasswordRequest", "ChangePasswordRequest",
    "RevokeSessionRequest", "RevokeApiKeyRequest", "RotateApiKeyRequest",
    "CreateApiKeyRequest", "CreateUserRequest",
    # devices
    "DeviceDto", "DeviceStateDto", "DeviceMappingDto", "ExternalDeviceDto",
    "SetDeviceStateRequest",
    # plugins
    "PluginDto", "PluginDetailsDto", "PluginsDiscoverDto",
    "PluginUiContributionsDto", "UiPageContributionDto", "UiWidgetContributionDto",
    "DashboardCardDto", "DashboardCardsListDto",
    "PluginConfigDto", "SetPluginConfigRequest", "PluginServiceInvokeRequest",
    "PluginServiceInvokeResult",
    "LoadPluginRequest", "EnsureContainerRequest", "AutoLoadRequest",
    # operations
    "OperationDto", "ExecutionDto", "ExecutionAttemptDto", "ExecutionScheduleDto",
    "CreateOperationRequest", "CreateOperationResponse", "CancelRetryResponse",
    # inspector
    "DashboardSummaryDto", "RuntimeInfoDto", "ServiceDto", "HttpEndpointInfoDto",
    "WsEndpointInfoDto", "RuntimeEventDto", "IntegrationFlowDto",
    "InventorySnapshotDto", "SystemHealthDto", "OperationTypeDto",
    # agents
    "AgentDto", "DeploymentStatusDto", "DeploymentMetricsDto",
    "AgentHeartbeatDto", "AgentHealthCheckDto", "AgentLogsDto", "AgentStatusDto",
    "EnrollmentTokenDto", "ChecksumDto",
    "CreateEnrollmentTokenRequest", "BootstrapTokenRequest", "EnrollAgentRequest",
    "DeployAgentRequest", "HeartbeatRequest", "SubmitLogsRequest", "StartTerminalRequest",
    # credentials
    "CredentialDto", "TerminalSessionStartDto",
    "CreateCredentialRequest", "UpdateCredentialRequest",
    # ssh
    "SshSessionDto", "CreateSshSessionRequest",
    # storage
    "StorageNamespaceDto", "StorageNamespaceContentsDto",
    # marketplace
    "MarketplaceCatalogEntryDto", "InstalledPluginDto", "MarketplaceResultDto",
    "GitSourcesDto", "GitCatalogEntryDto",
    "InstallFromArchiveRequest", "InstallFromRegistryRequest", "UpdateFromRegistryRequest", "InstallFromGitRequest",
    "RemovePluginRequest", "UpdatePluginRequest", "SetGitSourcesRequest",
    "BuildGitCatalogRequest",
    # integrations
    "IntegrationDto", "IntegrationFlowDto",
    # presence
    "PresenceStatusDto",
    # skills
    "SkillDto", "SkillListDto", "SkillInvokeRequest", "SkillInvokeResult",
]
