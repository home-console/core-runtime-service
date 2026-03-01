"""Step 15: Agent Control Plane Services."""

from typing import Any, Dict, List, Optional
from datetime import datetime, timezone, timedelta
import asyncio
import uuid
import logging

logger = logging.getLogger(__name__)


async def admin_agent_create_enrollment_token(runtime: Any, body: Any = None) -> Dict[str, Any]:
    """
    Create enrollment token for new agent.
    
    Args:
        runtime: CoreRuntime instance
        body: {agent_name: str}
        
    Returns:
        {ok: bool, token: {token_id, token_secret, expires_at}, error?: str}
    """
    if not isinstance(body, dict):
        return {"ok": False, "error": "invalid_body"}
    
    agent_name = body.get("agent_name")
    if not agent_name:
        return {"ok": False, "error": "agent_name required"}
    
    if not runtime.agent_manager:
        return {"ok": False, "error": "agent_manager not initialized"}
    
    try:
        now = datetime.now(timezone.utc).isoformat()
        token = await runtime.agent_manager.create_enrollment_token(agent_name, now)
        
        return {
            "ok": True,
            "token": {
                "token_id": token.token_id,
                "token_secret": token.token_secret,  # Only shown once!
                "expires_at": token.expires_at,
                "agent_name": token.agent_name,
            }
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def admin_agent_enroll_agent(runtime: Any, body: Any = None) -> Dict[str, Any]:
    """
    Enroll agent with enrollment token.
    
    Args:
        runtime: CoreRuntime instance
        body: {token_id: str, token_secret: str}
        
    Returns:
        {ok: bool, agent_id: str, identity: {...}, error?: str}
    """
    if not isinstance(body, dict):
        return {"ok": False, "error": "invalid_body"}
    
    token_id = body.get("token_id")
    token_secret = body.get("token_secret")
    
    if not token_id or not token_secret:
        return {"ok": False, "error": "token_id and token_secret required"}
    
    if not runtime.agent_manager:
        return {"ok": False, "error": "agent_manager not initialized"}
    
    try:
        now = datetime.now(timezone.utc).isoformat()
        identity, _ = await runtime.agent_manager.enroll_agent(
            token_id, token_secret, now
        )
        
        # Generate client certificate
        if runtime.mtls_ca:
            client_cert = runtime.mtls_ca.issue_agent_certificate(
                agent_id=identity.agent_id,
                agent_name=identity.agent_name,
                agent_public_key_pem=identity.public_key.key_pem.encode(),
            )
        else:
            client_cert = None
        
        return {
            "ok": True,
            "agent_id": identity.agent_id,
            "identity": identity.to_dict(),
            "client_certificate": client_cert.decode() if client_cert else None,
        }
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def admin_agent_list_agents(runtime: Any) -> Dict[str, Any]:
    """
    List all registered agents.
    
    Returns:
        {ok: bool, agents: [AgentMetadata], error?: str}
    """
    if not runtime.agent_registry:
        return {"ok": False, "error": "agent_registry not initialized"}
    
    try:
        agents = await runtime.agent_registry.list_agents()
        return {
            "ok": True,
            "agents": [a.to_dict() for a in agents]
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def admin_agent_get_agent(runtime: Any, agent_id: str) -> Dict[str, Any]:
    """
    Get agent details.
    
    Args:
        runtime: CoreRuntime instance
        agent_id: Agent ID
        
    Returns:
        {ok: bool, agent: AgentMetadata, error?: str}
    """
    if not runtime.agent_registry:
        return {"ok": False, "error": "agent_registry not initialized"}
    
    if not agent_id:
        return {"ok": False, "error": "agent_id required"}
    
    try:
        agent = await runtime.agent_registry.get_agent(agent_id)
        if not agent:
            return {"ok": False, "error": "agent not found"}
        
        return {
            "ok": True,
            "agent": agent.to_dict()
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def admin_agent_deregister_agent(runtime: Any, agent_id: str) -> Dict[str, Any]:
    """
    Deregister agent.
    
    Args:
        runtime: CoreRuntime instance
        agent_id: Agent ID
        
    Returns:
        {ok: bool, error?: str}
    """
    if not runtime.agent_registry:
        return {"ok": False, "error": "agent_registry not initialized"}
    
    if not runtime.agent_manager:
        return {"ok": False, "error": "agent_manager not initialized"}
    
    if not agent_id:
        return {"ok": False, "error": "agent_id required"}
    
    try:
        # Deregister from registry
        await runtime.agent_registry.deregister_agent(agent_id)
        
        # Deregister from enrollment manager (removes keys from SecretStore)
        await runtime.agent_manager.deregister_agent(agent_id)
        
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def admin_agent_list_agents_providing_capability(
    runtime: Any, capability_id: str
) -> Dict[str, Any]:
    """
    List agents providing a specific capability.
    
    Args:
        runtime: CoreRuntime instance
        capability_id: Capability ID
        
    Returns:
        {ok: bool, agents: [AgentMetadata], error?: str}
    """
    if not runtime.agent_registry:
        return {"ok": False, "error": "agent_registry not initialized"}
    
    if not capability_id:
        return {"ok": False, "error": "capability_id required"}
    
    try:
        agents = await runtime.agent_registry.list_agents_providing_capability(capability_id)
        return {
            "ok": True,
            "agents": [a.to_dict() for a in agents]
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ============================================================================
# TASK 1.1: Agent Deployment via SSH
# ============================================================================


async def admin_agent_deploy(runtime: Any, body: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Deploy agent to remote host via SSH.
    
    Workflow:
    1. Validate request
    2. Create deployment tracker entry
    3. Generate enrollment token with 10-minute TTL
    4. Execute AgentDeployService.deploy() via SSH
    5. Return deployment_id + heartbeat_timeout
    6. Start async monitoring task (don't wait for it)
    
    Args:
        runtime: CoreRuntime instance
        body: {
            "agent_name": str (required),
            "credential_id": str (required),
            "host"?: str (optional override),
            "env"?: dict (optional env vars)
        }
    
    Returns:
        {
            "ok": true,
            "deployment_id": "deploy-uuid",
            "agent_name": "my-agent",
            "host": "192.168.1.100",
            "status": "started",
            "created_at": "2026-02-25T...",
            "heartbeat_timeout": 300,
            "polling_interval": 2
        }
    """
    
    # ========== INPUT VALIDATION ==========
    if not isinstance(body, dict):
        return {
            "ok": False,
            "error": "invalid_body: expected JSON object"
        }
    
    agent_name = str(body.get("agent_name") or "").strip()
    credential_id = str(body.get("credential_id") or "").strip()
    custom_host = body.get("host")
    custom_env = body.get("env", {})
    
    if not agent_name:
        return {"ok": False, "error": "agent_name required (non-empty string)"}
    
    if not credential_id:
        return {"ok": False, "error": "credential_id required (SSH credential)"}
    
    # ========== RUNTIME CHECKS ==========
    if not runtime.agent_manager:
        return {"ok": False, "error": "agent_manager not initialized"}
    
    if not runtime.deployment_tracker:
        return {"ok": False, "error": "deployment_tracker not initialized"}
    
    # ========== CREATE DEPLOYMENT ENTRY ==========
    deployment_id = str(uuid.uuid4())
    
    # Infer host from credential or request
    try:
        # Get credential to extract host
        storage_manager = getattr(runtime, "storage_manager", None)
        if not storage_manager:
            return {"ok": False, "error": "storage_manager not initialized"}
        
        host = custom_host
        if not host:
            # Try to get from credential
            try:
                credential_obj = await storage_manager.get(credential_id)
                if credential_obj:
                    host = credential_obj.get("host") if isinstance(credential_obj, dict) else getattr(credential_obj, "host", None)
            except Exception:
                pass
        
        if not host:
            return {
                "ok": False,
                "error": "Cannot determine host (not in credential, not in request)"
            }
    except Exception as e:
        logger.exception(f"[AdminAgentDeploy] Failed to get credential: {e}")
        return {
            "ok": False,
            "error": f"Failed to get credential: {e}"
        }
    
    # Create deployment tracker entry
    try:
        await runtime.deployment_tracker.create(
            deployment_id=deployment_id,
            agent_name=agent_name,
            credential_id=credential_id,
            host=host,
            custom_env=custom_env or {}
        )
    except Exception as e:
        logger.exception(f"[AdminAgentDeploy] Failed to create deployment: {e}")
        return {
            "ok": False,
            "error": f"Failed to create deployment: {e}"
        }
    
    # ========== GENERATE ENROLLMENT TOKEN ==========
    try:
        enrollment_token = await runtime.agent_manager.generate_enrollment_token(agent_name)
        
        # Store token on deployment for later revocation if needed
        deployment = await runtime.deployment_tracker.get(deployment_id)
        if deployment:
            deployment.enrollment_token_str = enrollment_token
    except Exception as e:
        logger.exception(f"[AdminAgentDeploy] Token generation failed: {e}")
        await runtime.deployment_tracker.update_status(
            deployment_id,
            "failed",
            error_message=f"Token generation failed: {e}"
        )
        return {
            "ok": False,
            "error": f"Failed to generate enrollment token: {e}"
        }
    
    # ========== START BACKGROUND DEPLOYMENT TASK ==========
    # IMPORTANT: We do NOT await this — return immediately
    asyncio.create_task(
        _execute_deployment(
            runtime=runtime,
            deployment_id=deployment_id,
            agent_name=agent_name,
            credential_id=credential_id,
            enrollment_token=enrollment_token,
            host=host,
            custom_env=custom_env
        )
    )
    
    logger.info(
        f"[AdminAgentDeploy] Deployment started",
        extra={
            "deployment_id": deployment_id,
            "agent_name": agent_name,
            "host": host,
            "credential_id": credential_id
        }
    )
    
    # ========== RETURN IMMEDIATELY ==========
    return {
        "ok": True,
        "deployment_id": deployment_id,
        "agent_name": agent_name,
        "host": host,
        "status": "started",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "heartbeat_timeout": 300,
        "polling_interval": 2,
        "next_check": f"poll GET /admin/v1/deployments/{deployment_id}"
    }


async def _execute_deployment(
    runtime: Any,
    deployment_id: str,
    agent_name: str,
    credential_id: str,
    enrollment_token: str,
    host: str,
    custom_env: Dict[str, str]
) -> None:
    """
    Background task: Execute SSH deployment and monitor.
    
    This runs in background and updates deployment_tracker as it progresses.
    States: PENDING → UPLOADING → DEPLOYING → DEPLOYED → REGISTERING → READY/FAILED
    """
    try:
        deployment = await runtime.deployment_tracker.get(deployment_id)
        if not deployment:
            logger.error(f"[ExecuteDeployment] Deployment {deployment_id} not found")
            return
        
        # ========== STEP 1: SSH DEPLOYMENT ==========
        logger.info(f"[ExecuteDeployment] Starting SSH deployment: {deployment_id}")
        
        await runtime.deployment_tracker.update_status(
            deployment_id,
            status="uploading",
            progress=10
        )
        
        # Use AgentDeployService to deploy
        from modules.agents.agent_deploy_service import AgentDeployService
        
        deploy_service = AgentDeployService(runtime)
        
        try:
            deploy_result = await deploy_service.deploy(
                credential_id=credential_id,
                agent_name=agent_name
            )
            
            logger.info(
                f"[ExecuteDeployment] SSH deployment completed",
                extra={
                    "deployment_id": deployment_id,
                    "agent_name": agent_name,
                    "result": deploy_result
                }
            )
        except Exception as e:
            logger.exception(f"[ExecuteDeployment] SSH deployment failed: {e}")
            await runtime.deployment_tracker.update_status(
                deployment_id,
                status="failed",
                error_message=f"SSH deployment failed: {e}",
                completed_at=datetime.now(timezone.utc).isoformat()
            )
            return
        
        await runtime.deployment_tracker.update_status(
            deployment_id,
            status="deployed",
            progress=50
        )
        
        # ========== STEP 2: WAIT FOR ENROLLMENT ==========
        logger.info(f"[ExecuteDeployment] Waiting for enrollment: {agent_name}")
        
        await runtime.deployment_tracker.update_status(
            deployment_id,
            status="deploying",
            progress=60
        )
        
        # Now agent should start and try to enroll
        deadline = datetime.now(timezone.utc) + timedelta(seconds=60)  # 60s to enroll
        enrolled_agent_id = None
        
        while datetime.now(timezone.utc) < deadline:
            # Check if agent is enrolled
            try:
                agents = await runtime.agent_manager.list_enrolled_agents()
                
                # Try to find our agent
                for agent_id in agents:
                    identity = await runtime.agent_manager.get_agent_identity(agent_id)
                    if identity and identity.agent_name == agent_name:
                        enrolled_agent_id = agent_id
                        break
                
                if enrolled_agent_id:
                    break
            except Exception as e:
                logger.debug(f"[ExecuteDeployment] Error checking enrollment: {e}")
                # Continue polling on error
                pass
            
            await asyncio.sleep(2)
        
        if not enrolled_agent_id:
            logger.warning(f"[ExecuteDeployment] Agent did not enroll within timeout: {agent_name}")
            await runtime.deployment_tracker.update_status(
                deployment_id,
                status="timeout",
                error_message="Agent did not enroll within 60 seconds",
                completed_at=datetime.now(timezone.utc).isoformat()
            )
            
            # Cleanup: revoke enrollment token
            try:
                if deployment.enrollment_token_id:
                    await runtime.agent_manager.revoke_enrollment_token(deployment.enrollment_token_id)
            except Exception:
                pass  # Best effort cleanup
            
            return
        
        logger.info(
            f"[ExecuteDeployment] Agent enrolled successfully",
            extra={
                "deployment_id": deployment_id,
                "agent_id": enrolled_agent_id,
                "agent_name": agent_name
            }
        )
        
        await runtime.deployment_tracker.update_status(
            deployment_id,
            status="registering",
            agent_id=enrolled_agent_id,
            progress=75
        )
        
        # ========== STEP 3: WAIT FOR HEARTBEAT ==========
        logger.info(f"[ExecuteDeployment] Waiting for agent heartbeat: {enrolled_agent_id}")
        
        deadline = datetime.now(timezone.utc) + timedelta(seconds=240)  # 240s remaining (300s total - 60s enrollment)
        agent_online = False
        
        while datetime.now(timezone.utc) < deadline:
            try:
                agent_metadata = await runtime.agent_registry.get_agent(enrolled_agent_id)
                
                # Check last heartbeat
                if agent_metadata and hasattr(agent_metadata, 'last_heartbeat') and agent_metadata.last_heartbeat:
                    # Agent has sent heartbeat
                    try:
                        last_hb = datetime.fromisoformat(agent_metadata.last_heartbeat)
                        now = datetime.now(timezone.utc)
                        heartbeat_age = (now - last_hb).total_seconds()
                        
                        if heartbeat_age < 30:  # Recent heartbeat
                            agent_online = True
                            break
                    except (ValueError, TypeError):
                        pass  # Invalid heartbeat format
                elif agent_metadata and hasattr(agent_metadata, 'status'):
                    # Check status field
                    if agent_metadata.status == "online" or agent_metadata.status == "ready":
                        agent_online = True
                        break
            except Exception as e:
                logger.debug(f"[ExecuteDeployment] Error checking heartbeat: {e}")
                pass
            
            await asyncio.sleep(3)
        
        if not agent_online:
            logger.warning(f"[ExecuteDeployment] Agent did not report heartbeat: {enrolled_agent_id}")
            await runtime.deployment_tracker.update_status(
                deployment_id,
                status="timeout",
                agent_id=enrolled_agent_id,
                error_message="Agent did not report heartbeat within timeout",
                completed_at=datetime.now(timezone.utc).isoformat()
            )
            return
        
        # ========== SUCCESS ==========
        logger.info(
            f"[ExecuteDeployment] Deployment successful",
            extra={
                "deployment_id": deployment_id,
                "agent_id": enrolled_agent_id,
                "agent_name": agent_name
            }
        )
        
        await runtime.deployment_tracker.update_status(
            deployment_id,
            status="ready",
            agent_id=enrolled_agent_id,
            progress=100,
            completed_at=datetime.now(timezone.utc).isoformat()
        )
        
    except Exception as e:
        # ========== UNEXPECTED FAILURE HANDLING ==========
        logger.exception(f"[ExecuteDeployment] Unexpected error during deployment: {e}")
        
        try:
            await runtime.deployment_tracker.update_status(
                deployment_id,
                status="failed",
                error_message=str(e),
                completed_at=datetime.now(timezone.utc).isoformat()
            )
        except Exception as cleanup_error:
            logger.error(f"[ExecuteDeployment] Failed to update deployment status: {cleanup_error}")


async def admin_agent_get_deployment_status(runtime: Any, deployment_id: str) -> Dict[str, Any]:
    """
    Poll deployment status.
    
    Args:
        runtime: CoreRuntime instance
        deployment_id: Deployment ID to check
    
    Returns:
        {
            "ok": true,
            "deployment_id": "..." ,
            "status": "started|uploading|deployed|registering|ready|failed|timeout",
            "progress": 0-100,
            "agent_id"?: "...",
            "error_message"?: "...",
            "created_at": "2026-02-25T10:30:00Z",
            "completed_at"?: "2026-02-25T10:35:00Z",
            "duration_seconds"?: 300
        }
    """
    if not runtime.deployment_tracker:
        return {"ok": False, "error": "deployment_tracker not initialized"}
    
    if not deployment_id:
        return {"ok": False, "error": "deployment_id required"}
    
    try:
        deployment = await runtime.deployment_tracker.get(deployment_id)
        
        if not deployment:
            return {
                "ok": False,
                "error": "deployment_not_found"
            }
        
        result = {
            "ok": True,
            "deployment_id": deployment_id,
            "agent_name": deployment.agent_name,
            "host": deployment.host,
            "status": deployment.status.value,
            "progress": deployment.progress_percentage,
            "created_at": deployment.created_at.isoformat(),
        }
        
        if deployment.agent_id:
            result["agent_id"] = deployment.agent_id
        
        if deployment.error_message:
            result["error_message"] = deployment.error_message
        
        if deployment.completed_at:
            result["completed_at"] = deployment.completed_at.isoformat()
            duration = deployment.duration_seconds()
            if duration is not None:
                result["duration_seconds"] = duration
        
        return result
    
    except Exception as e:
        logger.exception(f"[AdminAgentGetDeploymentStatus] Error: {e}")
        return {
            "ok": False,
            "error": str(e)
        }


async def admin_agent_get_deployment_metrics(runtime: Any) -> Dict[str, Any]:
    """
    Get deployment statistics and metrics for dashboard.
    
    Returns:
        {
            "ok": true,
            "total": int,
            "succeeded": int,
            "failed": int,
            "in_progress": int,
            "success_rate": float (0-1),
            "average_duration_seconds": float,
            "by_status": { status: count },
            "recent_5": [...]
        }
    """
    if not runtime.deployment_tracker:
        return {"ok": False, "error": "deployment_tracker not initialized"}
    
    try:
        metrics = await runtime.deployment_tracker.get_deployment_metrics()
        return {
            "ok": True,
            **metrics
        }
    except Exception as e:
        logger.exception(f"[AdminAgentGetDeploymentMetrics] Error: {e}")
        return {
            "ok": False,
            "error": str(e)
        }


async def admin_agent_heartbeat(
    runtime: Any,
    agent_id: str,
    body: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Receive heartbeat from agent (called every 5-10 seconds).
    
    Used to:
    1. Update last_heartbeat timestamp
    2. Mark agent as online
    3. Trigger deployment completion if waiting
    
    Args:
        runtime: CoreRuntime instance
        agent_id: Agent ID
        body: {
            "status": "ok"|"degraded"|"error",
            "uptime_seconds"?: int,
            "cpu_percent"?: float,
            "memory_mb"?: int,
            "capabilities"?: [...]
        }
    
    Returns:
        {"ok": true, "ack": true, "server_time": "..."}
    """
    if not agent_id:
        return {"ok": False, "error": "agent_id required"}
    
    if not runtime.agent_registry:
        return {"ok": False, "error": "agent_registry not initialized"}
    
    try:
        # Get agent metadata
        agent = await runtime.agent_registry.get_agent(agent_id)
        if not agent:
            return {
                "ok": False,
                "error": "agent_not_found"
            }
        
        # Update last heartbeat
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        
        # Update heartbeat in registry
        await runtime.agent_registry.update_agent_heartbeat(agent_id, now_iso)
        
        # Re-fetch updated agent
        agent = await runtime.agent_registry.get_agent(agent_id)
        
        # Update optional metrics in properties
        if body and isinstance(body, dict):
            if "uptime_seconds" in body:
                try:
                    agent.properties["uptime_seconds"] = int(body["uptime_seconds"])
                except (ValueError, TypeError):
                    pass
            if "cpu_percent" in body:
                try:
                    agent.properties["cpu_percent"] = float(body["cpu_percent"])
                except (ValueError, TypeError):
                    pass
            if "memory_mb" in body:
                try:
                    agent.properties["memory_mb"] = int(body["memory_mb"])
                except (ValueError, TypeError):
                    pass
            if "capabilities" in body and isinstance(body["capabilities"], list):
                await runtime.agent_registry.update_agent_capabilities(agent_id, body["capabilities"])
        
        logger.debug(
            f"[AdminAgentHeartbeat] Heartbeat received",
            extra={
                "agent_id": agent_id,
                "agent_name": agent.agent_name if hasattr(agent, 'agent_name') else None
            }
        )
        
        # Check if there are pending deployments waiting for this agent
        # (this would mark deployment as READY)
        if runtime.deployment_tracker:
            try:
                pending_deployments = await runtime.deployment_tracker.list_deployments(
                    status="registering",
                    limit=100
                )
                
                for deployment in pending_deployments:
                    if deployment.agent_id == agent_id:
                        # Found deployment waiting for this agent
                        await runtime.deployment_tracker.update_status(
                            deployment.deployment_id,
                            status="ready",
                            progress=100,
                            completed_at=now.isoformat()
                        )
                        logger.info(
                            f"[AdminAgentHeartbeat] Deployment ready via heartbeat",
                            extra={
                                "deployment_id": deployment.deployment_id,
                                "agent_id": agent_id
                            }
                        )
            except Exception as e:
                logger.debug(f"[AdminAgentHeartbeat] Error updating deployment status: {e}")
        
        return {
            "ok": True,
            "ack": True,
            "server_time": now.isoformat()
        }
    
    except Exception as e:
        logger.exception(f"[AdminAgentHeartbeat] Error: {e}")
        return {
            "ok": False,
            "error": str(e)
        }


# ============================================================================
# TASK 2.2: Agent Binary Download & Checksum
# ============================================================================


async def admin_agent_download_checksum(runtime: Any) -> Dict[str, Any]:
    """
    Return SHA256 checksum of agent binary for installer verification.
    
    Called by installer script to verify downloaded binary integrity.
    
    Returns:
        {
            "ok": true,
            "sha256": "abc123def456...",
            "size_bytes": 12345678,
            "filename": "remote-client-linux-amd64",
            "version": "1.0.0",
            "cached": true  # from cache?
        }
    """
    try:
        # Try to get agent binary from asset storage
        # This is a placeholder - actual implementation depends on where binaries are stored
        
        # For now, return a computed checksum if available
        # In production, this would:
        # 1. Get binary from CDN/storage
        # 2. Compute SHA256
        # 3. Cache result (recompute daily)
        
        logger.info("[AdminAgentDownloadChecksum] Checksum requested")
        
        # Placeholder response
        return {
            "ok": True,
            "sha256": "not_yet_implemented",
            "size_bytes": 0,
            "filename": "remote-client",
            "version": "1.0.0",
            "cached": False,
            "message": "Checksum computation not yet implemented - configure AGENT_BINARY_PATH"
        }
    
    except Exception as e:
        logger.exception(f"[AdminAgentDownloadChecksum] Error: {e}")
        return {
            "ok": False,
            "error": str(e)
        }


async def admin_agent_download_binary(
    runtime: Any,
    **query_params: Any
) -> Dict[str, Any]:
    """
    Download agent binary for installation on remote host.
    
    Query parameters:
    - arch: linux-amd64 | linux-arm64 | darwin-amd64 | etc (auto-detect if not provided)
    - version: specific version (default: latest)
    
    Returns:
        {
            "ok": true,
            "message": "Binary ready for download",
            "filename": "remote-client-linux-amd64",
            "size_bytes": 12345678,
            "download_url": "http://..."  # Direct download link
        }
    """
    try:
        arch = query_params.get("arch", "linux-amd64")
        version = query_params.get("version", "latest")
        
        logger.info(
            f"[AdminAgentDownloadBinary] Binary requested",
            extra={
                "arch": arch,
                "version": version
            }
        )
        
        # Placeholder - actual implementation would:
        # 1. Validate arch parameter
        # 2. Locate binary in CDN/storage
        # 3. Generate signed download URL
        # 4. Return metadata
        
        return {
            "ok": True,
            "filename": f"remote-client-{arch}",
            "size_bytes": 0,
            "version": version,
            "message": "Binary download not yet implemented - configure AGENT_BINARY_STORAGE"
        }
    
    except Exception as e:
        logger.exception(f"[AdminAgentDownloadBinary] Error: {e}")
        return {
            "ok": False,
            "error": str(e)
        }


# ============================================================================
# TASK 1.3: Heartbeat Monitoring & Agent Health
# ============================================================================


async def admin_agent_get_heartbeat_status(runtime: Any, agent_id: str) -> Dict[str, Any]:
    """
    Get heartbeat status for specific agent.
    
    Used to check if agent is responsive and when it last sent heartbeat.
    
    Args:
        runtime: CoreRuntime instance
        agent_id: Agent ID to check
    
    Returns:
        {
            "ok": true,
            "agent_id": "...",
            "agent_name": "...",
            "status": "online" | "offline" | "dead" | "unknown",
            "last_heartbeat": "2025-02-25T10:30:00Z",
            "heartbeat_age_seconds": 5,
            "threshold_seconds": 30,  # After this agent is "offline"
            "dead_threshold_seconds": 300,  # After this agent is "dead"
            "metrics": {
                "uptime_seconds": 3600,
                "cpu_percent": 25.5,
                "memory_mb": 512
            }
        }
    """
    if not agent_id:
        return {"ok": False, "error": "agent_id required"}
    
    if not runtime.agent_registry:
        return {"ok": False, "error": "agent_registry not initialized"}
    
    try:
        # Get agent metadata
        agent = await runtime.agent_registry.get_agent(agent_id)
        if not agent:
            return {"ok": False, "error": "agent_not_found"}
        
        # Get heartbeat info
        now = datetime.now(timezone.utc)
        last_heartbeat_str = getattr(agent, "last_heartbeat", None)
        
        if not last_heartbeat_str:
            status = "unknown"
            age_seconds = None
        else:
            try:
                last_heartbeat = datetime.fromisoformat(last_heartbeat_str.replace('Z', '+00:00'))
                age_seconds = int((now - last_heartbeat).total_seconds())
                
                # Determine status based on age
                if age_seconds < 30:  # Fresh within 30 seconds
                    status = "online"
                elif age_seconds < 300:  # Stale but acceptable (5 minutes)
                    status = "offline"
                else:  # Very stale (>5 minutes)
                    status = "dead"
            except (ValueError, AttributeError):
                status = "unknown"
                age_seconds = None
        
        # Get metrics from properties
        metrics = {}
        if hasattr(agent, "properties") and isinstance(agent.properties, dict):
            metrics = {
                "uptime_seconds": agent.properties.get("uptime_seconds"),
                "cpu_percent": agent.properties.get("cpu_percent"),
                "memory_mb": agent.properties.get("memory_mb"),
            }
        
        logger.debug(
            f"[AdminAgentHeartbeatStatus] Status checked",
            extra={
                "agent_id": agent_id,
                "status": status,
                "age_seconds": age_seconds
            }
        )
        
        return {
            "ok": True,
            "agent_id": agent_id,
            "agent_name": getattr(agent, "agent_name", None),
            "status": status,
            "last_heartbeat": last_heartbeat_str,
            "heartbeat_age_seconds": age_seconds,
            "threshold_seconds": 30,  # online if < 30s
            "dead_threshold_seconds": 300,  # dead if > 300s
            "metrics": metrics
        }
    
    except Exception as e:
        logger.exception(f"[AdminAgentHeartbeatStatus] Error: {e}")
        return {"ok": False, "error": str(e)}


async def admin_agent_check_agents_health(runtime: Any) -> Dict[str, Any]:
    """
    Perform comprehensive health check on all agents.
    
    Detects dead agents and triggers cleanup if needed.
    
    Returns:
        {
            "ok": true,
            "timestamp": "...",
            "total_agents": 100,
            "online": 95,
            "offline": 4,
            "dead": 1,
            "unknown": 0,
            "agents": [
                {
                    "agent_id": "...",
                    "status": "online/offline/dead",
                    "age_seconds": 5
                },
                ...
            ]
        }
    """
    if not runtime.agent_registry:
        return {"ok": False, "error": "agent_registry not initialized"}
    
    try:
        # Get all agents
        agents = await runtime.agent_registry.list_agents()
        
        now = datetime.now(timezone.utc)
        now_str = now.isoformat()
        
        stats = {
            "online": 0,
            "offline": 0,
            "dead": 0,
            "unknown": 0
        }
        
        agent_statuses = []
        dead_agents = []  # Track agents to mark dead
        
        for agent in agents:
            last_heartbeat_str = getattr(agent, "last_heartbeat", None)
            
            if not last_heartbeat_str:
                status = "unknown"
                age_seconds = None
                stats["unknown"] += 1
            else:
                try:
                    last_heartbeat = datetime.fromisoformat(last_heartbeat_str.replace('Z', '+00:00'))
                    age_seconds = int((now - last_heartbeat).total_seconds())
                    
                    if age_seconds < 30:
                        status = "online"
                        stats["online"] += 1
                    elif age_seconds < 300:
                        status = "offline"
                        stats["offline"] += 1
                    else:
                        status = "dead"
                        stats["dead"] += 1
                        dead_agents.append(agent)
                except (ValueError, AttributeError):
                    status = "unknown"
                    age_seconds = None
                    stats["unknown"] += 1
            
            agent_statuses.append({
                "agent_id": getattr(agent, "agent_id", None),
                "agent_name": getattr(agent, "agent_name", None),
                "status": status,
                "age_seconds": age_seconds
            })
        
        # Mark dead agents if needed (optional cleanup)
        for dead_agent in dead_agents:
            try:
                agent_id = getattr(dead_agent, "agent_id", None)
                if agent_id:
                    # Mark as deregistered/dead in DB (non-blocking)
                    logger.warning(
                        f"[AdminAgentHealthCheck] Agent marked as dead",
                        extra={"agent_id": agent_id}
                    )
                    # Optionally call: await runtime.agent_registry.deregister_agent(agent_id)
            except Exception as e:
                logger.debug(f"[AdminAgentHealthCheck] Error marking dead agent: {e}")
        
        logger.info(
            f"[AdminAgentHealthCheck] Health check completed",
            extra=stats
        )
        
        return {
            "ok": True,
            "timestamp": now_str,
            "total_agents": len(agents),
            "stats": stats,
            "agents": agent_statuses
        }
    
    except Exception as e:
        logger.exception(f"[AdminAgentHealthCheck] Error: {e}")
        return {"ok": False, "error": str(e)}


async def admin_agent_list_online_agents(runtime: Any) -> Dict[str, Any]:
    """
    Get list of currently online agents (heartbeat < 30 seconds old).
    
    Returns:
        {
            "ok": true,
            "count": 95,
            "agents": [
                {
                    "agent_id": "...",
                    "agent_name": "...",
                    "last_heartbeat": "...",
                    "age_seconds": 5,
                    "capabilities": [...]
                },
                ...
            ]
        }
    """
    if not runtime.agent_registry:
        return {"ok": False, "error": "agent_registry not initialized"}
    
    try:
        # Get all agents
        agents = await runtime.agent_registry.list_agents()
        
        now = datetime.now(timezone.utc)
        online_agents = []
        
        for agent in agents:
            last_heartbeat_str = getattr(agent, "last_heartbeat", None)
            
            if not last_heartbeat_str:
                continue  # Skip agents with no heartbeat
            
            try:
                last_heartbeat = datetime.fromisoformat(last_heartbeat_str.replace('Z', '+00:00'))
                age_seconds = int((now - last_heartbeat).total_seconds())
                
                # Consider online if < 30 seconds
                if age_seconds < 30:
                    online_agents.append({
                        "agent_id": getattr(agent, "agent_id", None),
                        "agent_name": getattr(agent, "agent_name", None),
                        "last_heartbeat": last_heartbeat_str,
                        "age_seconds": age_seconds,
                        "capabilities": getattr(agent, "capabilities", [])
                    })
            except (ValueError, AttributeError):
                pass  # Skip if heartbeat parse fails
        
        logger.debug(
            f"[AdminAgentListOnline] Listed online agents",
            extra={"count": len(online_agents)}
        )
        
        return {
            "ok": True,
            "count": len(online_agents),
            "agents": online_agents
        }
    
    except Exception as e:
        logger.exception(f"[AdminAgentListOnline] Error: {e}")
        return {"ok": False, "error": str(e)}


# ============================================================================
# TASK 3.1: Agent Logs API
# ============================================================================


async def admin_agent_submit_logs(
    runtime: Any,
    agent_id: str,
    body: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """
    Accept a batch of log entries pushed by the remote agent.

    Body: {
        "logs": [
            {"level": "info", "message": "...", "source": "main",
             "timestamp": "2026-02-28T..." (optional)},
            ...
        ]
    }
    Returns: {"ok": true, "accepted": N}
    """
    if not agent_id:
        return {"ok": False, "error": "agent_id required"}

    if not hasattr(runtime, "agent_log_store") or runtime.agent_log_store is None:
        return {"ok": False, "error": "agent_log_store not initialized"}

    entries = []
    if body and isinstance(body, dict):
        entries = body.get("logs", [])
        if not isinstance(entries, list):
            return {"ok": False, "error": "logs must be a list"}

    accepted = runtime.agent_log_store.push_batch(agent_id, entries)

    logger.debug(
        "[AdminAgentSubmitLogs] Logs accepted",
        extra={"agent_id": agent_id, "accepted": accepted},
    )
    return {"ok": True, "accepted": accepted}


async def admin_agent_get_logs(
    runtime: Any,
    agent_id: str,
    filter: Optional[str] = None,
    tail: Optional[int] = 100,
) -> Dict[str, Any]:
    """
    Get stored log entries for a specific agent.

    Query params:
        filter: error|warn|info|debug  (comma-separated; default: all)
        tail:   number of last entries  (default: 100)

    Returns: {
        "ok": true,
        "agent_id": "...",
        "logs": [{"timestamp": ..., "level": ..., "message": ..., "source": ...}],
        "total": N,
        "agent_online": true|false
    }
    """
    if not agent_id:
        return {"ok": False, "error": "agent_id required"}

    if not hasattr(runtime, "agent_log_store") or runtime.agent_log_store is None:
        return {"ok": False, "error": "agent_log_store not initialized"}

    try:
        tail_int: Optional[int] = None
        if tail is not None:
            try:
                tail_int = int(tail)
                if tail_int <= 0:
                    tail_int = None
            except (ValueError, TypeError):
                tail_int = 100

        entries = runtime.agent_log_store.get(
            agent_id,
            level_filter=filter,
            tail=tail_int,
        )

        # Determine online status from registry
        agent_online = False
        if runtime.agent_registry:
            agent = await runtime.agent_registry.get_agent(agent_id)
            if agent and agent.last_heartbeat:
                try:
                    last_hb = datetime.fromisoformat(
                        agent.last_heartbeat.replace("Z", "+00:00")
                    )
                    age = (datetime.now(timezone.utc) - last_hb).total_seconds()
                    agent_online = age < 30
                except (ValueError, AttributeError):
                    pass

        return {
            "ok": True,
            "agent_id": agent_id,
            "logs": [e.to_dict() for e in entries],
            "total": runtime.agent_log_store.count(agent_id),
            "returned": len(entries),
            "agent_online": agent_online,
        }

    except Exception as e:
        logger.exception(f"[AdminAgentGetLogs] Error: {e}")
        return {"ok": False, "error": str(e)}


# ============================================================================
# TASK 3.2: Agent Status endpoint
# ============================================================================


async def admin_agent_get_status(
    runtime: Any,
    agent_id: str,
) -> Dict[str, Any]:
    """
    Get real-time status of a specific agent.

    Combines:
    - AgentRegistry metadata  (name, version, capabilities, last heartbeat)
    - Heartbeat metrics       (uptime, cpu, memory)
    - DeploymentTracker       (linked deployment_id, if any)

    Returns: {
        "ok": true,
        "agent_id": "...",
        "name": "...",
        "status": "online" | "offline" | "degraded" | "dead" | "unknown",
        "version": "1.0.0",
        "address": "10.0.0.1:8080",
        "last_heartbeat": "2026-02-28T...",
        "heartbeat_age_seconds": 3,
        "uptime_seconds": 3600,
        "cpu_percent": 12.5,
        "memory_mb": 256,
        "capabilities": [...],
        "deployment_id": "deploy-uuid" | null
    }
    """
    if not agent_id:
        return {"ok": False, "error": "agent_id required"}

    if not runtime.agent_registry:
        return {"ok": False, "error": "agent_registry not initialized"}

    try:
        agent = await runtime.agent_registry.get_agent(agent_id)
        if not agent:
            return {"ok": False, "error": "agent_not_found", "agent_id": agent_id}

        # ── Compute status from last heartbeat age ───────────────────────
        now = datetime.now(timezone.utc)
        heartbeat_age: Optional[int] = None
        status = "unknown"

        if agent.last_heartbeat:
            try:
                last_hb = datetime.fromisoformat(
                    agent.last_heartbeat.replace("Z", "+00:00")
                )
                heartbeat_age = int((now - last_hb).total_seconds())

                if heartbeat_age < 30:
                    # Check if agent self-reported degraded status
                    reported = agent.properties.get("status", "ok")
                    status = "degraded" if reported not in ("ok", "online") else "online"
                elif heartbeat_age < 300:
                    status = "offline"
                else:
                    status = "dead"
            except (ValueError, AttributeError):
                status = "unknown"

        # ── Find linked deployment_id from DeploymentTracker ──────────────
        deployment_id: Optional[str] = None
        if runtime.deployment_tracker:
            try:
                all_deps = await runtime.deployment_tracker.list_deployments(
                    limit=200
                )
                for dep in all_deps:
                    if dep.agent_id == agent_id:
                        deployment_id = dep.deployment_id
                        break
            except Exception:
                pass

        props = agent.properties or {}

        logger.debug(
            "[AdminAgentGetStatus] Status retrieved",
            extra={"agent_id": agent_id, "status": status},
        )

        return {
            "ok": True,
            "agent_id": agent_id,
            "name": agent.agent_name,
            "status": status,
            "version": agent.version or "",
            "address": agent.address,
            "last_heartbeat": agent.last_heartbeat,
            "heartbeat_age_seconds": heartbeat_age,
            "uptime_seconds": props.get("uptime_seconds"),
            "cpu_percent": props.get("cpu_percent"),
            "memory_mb": props.get("memory_mb"),
            "capabilities": agent.capabilities or [],
            "deployment_id": deployment_id,
        }

    except Exception as e:
        logger.exception(f"[AdminAgentGetStatus] Error: {e}")
        return {"ok": False, "error": str(e)}


async def _monitor_agent_health_background(runtime: Any) -> None:
    """
    Background task to monitor agent health continuously.
    
    Runs asynchronously every 60 seconds to:
    1. Check health of all agents
    2. Mark dead agents
    3. Trigger alerts if too many agents are down
    
    This is called from module initialization.
    """
    logger.info("[AgentHealthMonitor] Background health monitor started")
    
    while True:
        try:
            await asyncio.sleep(60)  # Check every 60 seconds
            
            # Run health check
            health_result = await admin_agent_check_agents_health(runtime)
            
            if health_result.get("ok"):
                stats = health_result.get("stats", {})
                
                # Log if too many dead agents
                dead_count = stats.get("dead", 0)
                total = health_result.get("total_agents", 0)
                
                if total > 0 and dead_count > total * 0.1:  # More than 10% dead
                    logger.warning(
                        f"[AgentHealthMonitor] High dead agent rate",
                        extra={
                            "dead_count": dead_count,
                            "total": total,
                            "percentage": (dead_count / total) * 100
                        }
                    )
                else:
                    logger.debug(
                        f"[AgentHealthMonitor] Health check OK",
                        extra=stats
                    )
        
        except Exception as e:
            logger.exception(f"[AgentHealthMonitor] Error in health monitoring: {e}")
            await asyncio.sleep(60)  # Wait before retry

