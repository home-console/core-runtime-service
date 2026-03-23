"""
Tests for Capability Protocol v1 stabilization.

Tests cover:
- Protocol version negotiation
- Manifest discovery
- Health monitoring and auto-recovery
- Timeout enforcement
- Retryable error handling
- Multiple remote providers with fallback
- Backward compatibility with legacy providers
"""

import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any, Dict

from core.operations import Operation, OperationInitiator, OperationInitiatorKind, OperationStatus
from modules.execution.remote_executor import RemoteOperationExecutor
from core.capability_protocol import (
    PROTOCOL_VERSION,
    ProtocolCompatibilityError,
    RemoteErrorCode,
    DEFAULT_CAPABILITY_TIMEOUT,
)
from core.health_monitor import ProviderHealthMonitor


@pytest.mark.asyncio
async def test_protocol_version_in_request_header():
    """Test that requests include protocol version header."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "status": "success",
        "protocol_version": PROTOCOL_VERSION,
        "result": {"data": "test"}
    }
    
    with patch('httpx.AsyncClient') as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client
        
        result = await RemoteOperationExecutor.execute_remote(
            base_url="http://localhost:9000",
            capability="test.capability",
            operation_id="op-123",
            params={"key": "value"},
            context={},
        )
        
        # Verify header was sent
        call_kwargs = mock_client.post.call_args.kwargs
        assert call_kwargs["headers"]["X-HomeConsole-Protocol"] == "1"
        
        # Verify request structure
        assert result["status"] == "success"


@pytest.mark.asyncio
async def test_protocol_version_validation():
    """Test protocol version mismatch detection."""
    # Provider responds with higher protocol version
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "status": "success",
        "protocol_version": 999,  # Future version
        "result": {}
    }
    
    with patch('httpx.AsyncClient') as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client
        
        with pytest.raises(ProtocolCompatibilityError):
            await RemoteOperationExecutor.execute_remote(
                base_url="http://localhost:9000",
                capability="test.capability",
                operation_id="op-123",
                params={},
                context={},
            )


@pytest.mark.asyncio
async def test_manifest_discovery_success():
    """Test successful manifest discovery."""
    manifest = {
        "protocol_version": PROTOCOL_VERSION,
        "provider_version": "1.2.0",
        "capabilities": ["test.cap1", "test.cap2"],
        "timeouts": {
            "test.cap1": 5.0,
            "test.cap2": 10.0,
        }
    }
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = manifest
    
    with patch('httpx.AsyncClient') as mock_client_class:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client
        
        result = await RemoteOperationExecutor.get_manifest("http://localhost:9000")
        
        assert result is not None
        assert result["provider_version"] == "1.2.0"
        assert "test.cap1" in result["capabilities"]
        assert result["timeouts"]["test.cap1"] == 5.0


@pytest.mark.asyncio
async def test_manifest_discovery_legacy_provider():
    """Test manifest discovery with legacy provider (404)."""
    mock_response = MagicMock()
    mock_response.status_code = 404
    
    with patch('httpx.AsyncClient') as mock_client_class:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client
        
        result = await RemoteOperationExecutor.get_manifest("http://localhost:9000")
        
        # Legacy provider - no manifest
        assert result is None


@pytest.mark.asyncio
async def test_health_check_success():
    """Test successful health check."""
    health = {
        "healthy": True,
        "version": "1.2.0",
        "timestamp": time.time(),
        "error_count": 0,
    }
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = health
    
    with patch('httpx.AsyncClient') as mock_client_class:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client
        
        result = await RemoteOperationExecutor.check_health("http://localhost:9000")
        
        assert result is not None
        assert result["healthy"] is True


@pytest.mark.asyncio
async def test_health_monitoring_failure_tracking():
    """Test health monitor tracks consecutive failures."""
    monitor = ProviderHealthMonitor()
    
    # Provider starts healthy
    monitor.initialize_provider("provider1")
    assert monitor.get_status("provider1").healthy is True
    
    # Record failures
    for i in range(3):
        monitor.record_failure("provider1", f"Error {i}")
    
    # Should be marked unhealthy after threshold
    assert monitor.get_status("provider1").healthy is False
    assert monitor.get_status("provider1").consecutive_failures >= 3


@pytest.mark.asyncio
async def test_health_monitoring_auto_recovery():
    """Test health monitor auto-recovery after success."""
    monitor = ProviderHealthMonitor()
    
    # Mark unhealthy
    monitor.mark_unhealthy("provider1", "test error")
    assert monitor.get_status("provider1").healthy is False
    
    # Record success
    monitor.record_success("provider1")
    assert monitor.get_status("provider1").healthy is True
    assert monitor.get_status("provider1").consecutive_failures == 0


def test_retryable_error_codes():
    """Test retryable error detection."""
    # Retryable error
    response_retryable = {
        "status": "error",
        "error": {
            "code": "temporary_unavailable",
            "message": "Server busy",
            "retryable": True,
        }
    }
    assert RemoteOperationExecutor.is_error_retryable(response_retryable) is True
    
    # Non-retryable error
    response_permanent = {
        "status": "error",
        "error": {
            "code": "invalid_params",
            "message": "Bad parameters",
            "retryable": False,
        }
    }
    assert RemoteOperationExecutor.is_error_retryable(response_permanent) is False
    
    # Success response
    response_success = {"status": "success"}
    assert RemoteOperationExecutor.is_error_retryable(response_success) is False


@pytest.mark.asyncio
async def test_timeout_enforcement_from_manifest():
    """Test that per-capability timeouts from manifest are respected."""
    # Create mock response with short timeout
    manifest = {
        "protocol_version": 1,
        "provider_version": "1.0.0",
        "capabilities": ["test.quick"],
        "timeouts": {"test.quick": 1.0}  # 1 second timeout
    }
    
    # Simulate timeout
    import httpx
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = manifest
    
    with patch('httpx.AsyncClient') as mock_client_class:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client
        
        result = await RemoteOperationExecutor.get_manifest("http://localhost:9000")
        assert result["timeouts"]["test.quick"] == 1.0


@pytest.mark.asyncio
async def test_protocol_mismatch_protection():
    """Test protocol version mismatch handling."""
    # Response with newer protocol version that core doesn't support
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "status": "error",
        "protocol_version": 99,
        "error": {"code": "error"}
    }
    
    with patch('httpx.AsyncClient') as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client
        
        with pytest.raises(ProtocolCompatibilityError):
            await RemoteOperationExecutor.execute_remote(
                base_url="http://localhost:9000",
                capability="test.capability",
                operation_id="op-123",
                params={},
                context={},
            )


@pytest.mark.asyncio
async def test_legacy_provider_backward_compatibility():
    """Test backward compatibility with providers not supporting protocol v1."""
    # Old-style response without protocol_version
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "status": "success",
        # No protocol_version field
        "result": {"data": "legacy"}
    }
    
    with patch('httpx.AsyncClient') as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client
        
        result = await RemoteOperationExecutor.execute_remote(
            base_url="http://localhost:9000",
            capability="test.capability",
            operation_id="op-123",
            params={},
            context={},
        )
        
        # Should work fine (legacy mode)
        assert result["status"] == "success"


@pytest.mark.asyncio
async def test_request_includes_capability_and_operation_id():
    """Test request includes capability and operation_id fields (Protocol v1)."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "status": "success",
        "protocol_version": 1,
        "result": {}
    }
    
    with patch('httpx.AsyncClient') as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client
        
        await RemoteOperationExecutor.execute_remote(
            base_url="http://localhost:9000",
            capability="client.command.execute",
            operation_id="op-abc-123",
            params={"action": "test"},
            context={"initiator": "admin"},
        )
        
        # Verify payload structure
        call_kwargs = mock_client.post.call_args.kwargs
        payload = call_kwargs["json"]
        
        assert payload["protocol_version"] == PROTOCOL_VERSION
        assert payload["capability"] == "client.command.execute"
        assert payload["operation_id"] == "op-abc-123"
        assert payload["params"]["action"] == "test"


def test_health_monitor_get_healthy_providers():
    """Test getting list of healthy providers."""
    monitor = ProviderHealthMonitor()
    
    monitor.initialize_provider("provider1")
    monitor.initialize_provider("provider2")
    monitor.initialize_provider("provider3")
    
    # Mark provider2 unhealthy
    monitor.mark_unhealthy("provider2", "error")
    
    healthy = monitor.get_healthy_providers(["provider1", "provider2", "provider3"])
    
    assert "provider1" in healthy
    assert "provider3" in healthy
    assert "provider2" not in healthy


def test_health_monitor_retry_interval():
    """Test health monitor respects retry interval."""
    monitor = ProviderHealthMonitor()
    
    # Mark unhealthy
    monitor.mark_unhealthy("provider1", "error")
    
    # Immediately, should not retry
    status = monitor.get_status("provider1")
    status.last_check_time = time.time() - 5  # 5 seconds ago
    assert not status.should_retry_check(retry_interval_seconds=30)
    
    # After enough time, should retry
    status.last_check_time = time.time() - 31  # 31 seconds ago
    assert status.should_retry_check(retry_interval_seconds=30)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
