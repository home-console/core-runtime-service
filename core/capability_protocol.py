"""
Capability Protocol v1 - Production-grade specification for capability providers.

Enables:
- Version negotiation between core and providers
- Manifest discovery and capability listing
- Health monitoring and auto-recovery
- Retryable error handling
- Timeout enforcement per capability
- Remote provider marketplace compatibility

Protocol versions and contracts are immutable by design.
"""

from typing import TypedDict, Optional, List, Dict, Any
from dataclasses import dataclass
from enum import Enum
import time


# ============================================================================
# PROTOCOL VERSION
# ============================================================================

PROTOCOL_VERSION = 1  # Current supported version
PROTOCOL_HEADER = "X-HomeConsole-Protocol"


# ============================================================================
# REQUEST/RESPONSE SPECIFICATIONS
# ============================================================================

class CapabilityExecuteRequest(TypedDict, total=False):
    """Standard request to /capability/execute endpoint."""
    protocol_version: int  # Required: must match or fail
    capability: str        # Required: capability type being invoked
    operation_id: str      # Required: unique operation ID for tracing
    params: Dict[str, Any]      # Optional: capability parameters
    context: Dict[str, Any]     # Optional: execution context


class CapabilityErrorInfo(TypedDict, total=False):
    """Error details in capability response."""
    code: str       # Required: error code (MUST be stable)
    message: str    # Required: human-readable description
    retryable: bool # Optional: can client retry this request?
    details: Dict[str, Any]  # Optional: additional diagnostic info


class CapabilityExecuteResponse(TypedDict, total=False):
    """Standard response from /capability/execute endpoint."""
    status: str     # Required: "success" or "error"
    protocol_version: int  # Required: provider's protocol version
    result: Dict[str, Any]      # If status=success
    error: CapabilityErrorInfo  # If status=error


class CapabilityManifest(TypedDict, total=False):
    """Standard response from GET /capability/manifest endpoint."""
    protocol_version: int  # Required: this provider's protocol version
    provider_version: str  # Required: semantic version (e.g., "1.2.0")
    capabilities: List[str]  # Required: list of capability types supported
    timeouts: Dict[str, float]  # Optional: timeout_seconds per capability
    metadata: Dict[str, Any]     # Optional: provider-specific metadata


class CapabilityHealth(TypedDict, total=False):
    """Standard response from GET /capability/health endpoint."""
    healthy: bool      # Required: is provider currently healthy?
    version: str       # Required: provider version
    timestamp: float   # Required: check timestamp (unix seconds)
    error_count: int   # Optional: consecutive error count
    last_error: str    # Optional: last error message


# ============================================================================
# ERROR CODES - Standardized for marketplace compatibility
# ============================================================================

class RemoteErrorCode(Enum):
    """Standard error codes for remote capability execution."""
    
    # Client errors (4xx)
    INVALID_PROTOCOL = "invalid_protocol"          # protocol_version mismatch
    UNSUPPORTED_CAPABILITY = "unsupported_capability"  # capability not found
    INVALID_PARAMS = "invalid_params"              # parameters validation failed
    AUTH_FAILED = "auth_failed"                    # authentication/authorization failed
    
    # Server errors (5xx)
    INTERNAL_ERROR = "internal_error"              # provider internal error
    TIMEOUT = "timeout"                            # execution timeout
    NOT_IMPLEMENTED = "not_implemented"            # capability not yet implemented
    
    # System errors
    NOT_FOUND = "not_found"                        # resource not found
    CONFLICT = "conflict"                          # resource conflict
    
    # Transient errors (retryable)
    TEMPORARY_UNAVAILABLE = "temporary_unavailable"  # provider temporarily down
    RATE_LIMITED = "rate_limited"                  # too many requests
    RESOURCE_EXHAUSTED = "resource_exhausted"      # provider out of resources


# Define which errors are retryable
RETRYABLE_ERROR_CODES = {
    RemoteErrorCode.TEMPORARY_UNAVAILABLE.value,
    RemoteErrorCode.RATE_LIMITED.value,
    RemoteErrorCode.RESOURCE_EXHAUSTED.value,
    RemoteErrorCode.TIMEOUT.value,
}


# ============================================================================
# HEALTH MONITORING
# ============================================================================

@dataclass
class ProviderHealthStatus:
    """Current health status of a remote provider."""
    provider_name: str
    healthy: bool                  # Is provider healthy?
    last_check_time: float         # Unix timestamp of last health check
    consecutive_failures: int      # Consecutive errors
    last_error: Optional[str]      # Last error message
    version: Optional[str]         # Provider version from manifest
    
    def should_skip(self) -> bool:
        """Should this provider be skipped for new operations?"""
        return not self.healthy or self.consecutive_failures >= 3
    
    def should_retry_check(self, retry_interval_seconds: float = 30) -> bool:
        """Should health check be retried?"""
        if self.healthy:
            return False
        elapsed = time.time() - self.last_check_time
        return elapsed >= retry_interval_seconds


# ============================================================================
# PROVIDER METADATA (expanded for manifest)
# ============================================================================

@dataclass
class ProviderMetadata:
    """Extended provider metadata with protocol information."""
    plugin_name: str
    provider_type: str  # "local" or "remote"
    protocol_version: int = PROTOCOL_VERSION
    provider_version: Optional[str] = None  # e.g., "1.2.0"
    health: Optional[ProviderHealthStatus] = None
    remote_config: Optional[Dict[str, Any]] = None
    timeouts: Dict[str, float] = None  # capability -> timeout_seconds
    capabilities: List[str] = None     # Manifest: capabilities this provider supports
    
    def __post_init__(self):
        if self.timeouts is None:
            self.timeouts = {}
        if self.capabilities is None:
            self.capabilities = []
    
    def is_compatible_with_protocol(self, core_version: int = PROTOCOL_VERSION) -> bool:
        """Check if provider uses compatible protocol version."""
        return self.protocol_version <= core_version
    
    def get_timeout_for_capability(self, capability_id: str, default: float = 10.0) -> float:
        """Get timeout for specific capability, with fallback."""
        return self.timeouts.get(capability_id, default)


# ============================================================================
# PROTOCOL COMPATIBILITY CHECKER
# ============================================================================

class ProtocolCompatibilityError(Exception):
    """Raised when protocol versions are incompatible."""
    def __init__(self, provider_version: int, core_version: int = PROTOCOL_VERSION):
        self.provider_version = provider_version
        self.core_version = core_version
        super().__init__(
            f"Protocol mismatch: provider v{provider_version} > core v{core_version}"
        )


def check_protocol_compatibility(
    response_data: Dict[str, Any],
    core_version: int = PROTOCOL_VERSION
) -> None:
    """
    Validate protocol version in response.
    
    Raises:
        ProtocolCompatibilityError: if provider version > core version
        ValueError: if response missing required fields
    """
    protocol_version = response_data.get("protocol_version")
    
    # Legacy mode: if missing, assume v1
    if protocol_version is None:
        return
    
    if not isinstance(protocol_version, int):
        raise ValueError(f"Invalid protocol_version type: {type(protocol_version)}")
    
    if protocol_version > core_version:
        raise ProtocolCompatibilityError(protocol_version, core_version)


def is_retryable_error(error_code: str) -> bool:
    """Check if error code is retryable."""
    return error_code in RETRYABLE_ERROR_CODES


# ============================================================================
# DEFAULTS AND LIMITS
# ============================================================================

# Default timeouts
DEFAULT_CAPABILITY_TIMEOUT = 10.0  # seconds
DEFAULT_MANIFEST_TIMEOUT = 5.0     # seconds
DEFAULT_HEALTH_CHECK_TIMEOUT = 3.0 # seconds

# Health monitoring
HEALTH_CHECK_FAILURE_THRESHOLD = 3  # failures before marking unhealthy
HEALTH_CHECK_RETRY_INTERVAL = 30    # seconds before retrying unhealthy provider

# Retry strategy
MAX_RETRIES_PER_OPERATION = 2  # max remote providers to try
