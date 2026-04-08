"""Agent Control Plane Services."""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from core.adapters.storage_errors import STORAGE_BOUNDARY_ERRORS

logger = logging.getLogger(__name__)


async def admin_agent_create_enrollment_token(
    runtime: Any, body: Optional[Any] = None
) -> Dict[str, Any]:
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
            },
        }
    except STORAGE_BOUNDARY_ERRORS as e:
        logger.warning("admin_agent_create_enrollment_token storage error", exc_info=True)
        return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.exception("admin_agent_create_enrollment_token failed")
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
    except STORAGE_BOUNDARY_ERRORS as e:
        logger.warning("admin_agent_enroll_agent storage error", exc_info=True)
        return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.exception("admin_agent_enroll_agent failed")
        return {"ok": False, "error": str(e)}


async def admin_agent_generate_bootstrap_token(
    runtime: Any, body: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Generate one-time HMAC-signed enrollment token for installer / manual bootstrap.

    This is a thin admin wrapper around AgentEnrollmentManager.generate_enrollment_token().

    Args:
        runtime: CoreRuntime instance
        body: {agent_name: str}

    Returns:
        {ok: bool, token: str, agent_name: str, expires_at: str, error?: str}
    """
    if not isinstance(body, dict):
        return {"ok": False, "error": "invalid_body"}

    agent_name = str(body.get("agent_name") or "").strip()
    if not agent_name:
        return {"ok": False, "error": "agent_name required"}

    if not getattr(runtime, "agent_manager", None):
        return {"ok": False, "error": "agent_manager not initialized"}

    try:
        # AgentEnrollmentManager.generate_enrollment_token() internally uses TTL 600s (10 минут)
        token = await runtime.agent_manager.generate_enrollment_token(agent_name)
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=600)).isoformat()

        logger.info(
            "[AdminAgentBootstrapToken] Token generated",
            extra={"agent_name": agent_name},
        )

        return {
            "ok": True,
            "agent_name": agent_name,
            "token": token,
            "expires_at": expires_at,
        }
    except STORAGE_BOUNDARY_ERRORS as e:
        logger.warning(
            "[AdminAgentBootstrapToken] storage error generating token",
            exc_info=True,
        )
        return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.exception("[AdminAgentBootstrapToken] Error generating token")
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
        return {"ok": True, "agents": [a.to_dict() for a in agents]}
    except STORAGE_BOUNDARY_ERRORS as e:
        logger.warning("admin_agent_list_agents storage error", exc_info=True)
        return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.exception("admin_agent_list_agents failed")
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

        return {"ok": True, "agent": agent.to_dict()}
    except STORAGE_BOUNDARY_ERRORS as e:
        logger.warning("admin_agent_get_agent storage error", exc_info=True)
        return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.exception("admin_agent_get_agent failed")
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
    except STORAGE_BOUNDARY_ERRORS as e:
        logger.warning("admin_agent_deregister_agent storage error", exc_info=True)
        return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.exception("admin_agent_deregister_agent failed")
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
        agents = await runtime.agent_registry.list_agents_providing_capability(
            capability_id
        )
        return {"ok": True, "agents": [a.to_dict() for a in agents]}
    except STORAGE_BOUNDARY_ERRORS as e:
        logger.warning(
            "admin_agent_list_agents_providing_capability storage error",
            exc_info=True,
        )
        return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.exception("admin_agent_list_agents_providing_capability failed")
        return {"ok": False, "error": str(e)}


# ============================================================================
# TASK 1.1: Agent Deployment via SSH
# ============================================================================


async def admin_agent_deploy(
    runtime: Any, body: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
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
        return {"ok": False, "error": "invalid_body: expected JSON object"}

    agent_name = str(body.get("agent_name") or "").strip()
    credential_id = str(body.get("credential_id") or "").strip()
    custom_host = body.get("host")
    custom_core_url = (body.get("core_url") or "").strip() or None
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
        host = custom_host
        if not host:
            storage_manager = getattr(runtime, "storage_manager", None)
            if storage_manager is None:
                return {"ok": False, "error": "storage_manager not initialized"}

            def _extract_host(value: Any) -> Optional[str]:
                if value is None:
                    return None
                # Domain object path
                attr_host = getattr(value, "host", None)
                if isinstance(attr_host, str) and attr_host.strip():
                    return attr_host.strip()
                # Legacy dict path
                if isinstance(value, dict):
                    h = value.get("host")
                    if isinstance(h, str) and h.strip():
                        return h.strip()
                    md = value.get("metadata")
                    if isinstance(md, dict):
                        mh = md.get("host")
                        if isinstance(mh, str) and mh.strip():
                            return mh.strip()
                return None

            async def _read_legacy_raw_credential() -> Any:
                # Try the most permissive/legacy signatures first.
                for args, kwargs in [
                    ((credential_id,), {}),
                    (("credentials.meta", credential_id), {}),
                    (("credentials.meta", credential_id), {"target": "core"}),
                    (("credentials", credential_id), {}),
                ]:
                    try:
                        value = await storage_manager.get(*args, **kwargs)
                        if value is not None:
                            return value
                    except TypeError:
                        continue
                    except STORAGE_BOUNDARY_ERRORS:
                        logger.debug(
                            "admin_agent_deploy: legacy credential read storage error",
                            extra={"args": args},
                            exc_info=True,
                        )
                        continue
                    except Exception:
                        logger.debug(
                            "admin_agent_deploy: legacy credential read unexpected",
                            extra={"args": args},
                            exc_info=True,
                        )
                        continue
                return None

            try:
                from modules.credentials.repository import CredentialRepository

                secret_store = getattr(runtime, "secret_store", None)
                repo = CredentialRepository(
                    storage_manager=storage_manager, secret_store=secret_store
                )
                cred = await repo.get(credential_id)
                host = _extract_host(cred)
                if cred is None or not host:
                    raw_cred = await _read_legacy_raw_credential()
                    host = _extract_host(raw_cred)
                    if cred is None and raw_cred is None:
                        return {"ok": False, "error": f"Credential {credential_id} not found"}
            except Exception as e:
                if isinstance(e, STORAGE_BOUNDARY_ERRORS):
                    logger.debug(
                        "admin_agent_deploy: CredentialRepository.get storage error",
                        exc_info=True,
                    )
                else:
                    logger.warning(
                        "admin_agent_deploy: CredentialRepository.get failed",
                        exc_info=True,
                    )
                raw_cred = await _read_legacy_raw_credential()
                host = _extract_host(raw_cred)
                if raw_cred is None:
                    return {"ok": False, "error": f"Failed to read credential: {e}"}

        if not host:
            return {
                "ok": False,
                "error": "Cannot determine host: credential has no host field. Please set the host in the SSH credential.",
            }
    except STORAGE_BOUNDARY_ERRORS as e:
        logger.warning("[AdminAgentDeploy] credential resolution storage error", exc_info=True)
        return {"ok": False, "error": f"Failed to get credential: {e}"}
    except Exception as e:
        logger.exception("[AdminAgentDeploy] Failed to get credential")
        return {"ok": False, "error": f"Failed to get credential: {e}"}

    # Create deployment tracker entry
    try:
        await runtime.deployment_tracker.create(
            deployment_id=deployment_id,
            agent_name=agent_name,
            credential_id=credential_id,
            host=host,
            custom_env=custom_env or {},
        )
    except STORAGE_BOUNDARY_ERRORS as e:
        logger.warning("[AdminAgentDeploy] deployment_tracker.create storage error", exc_info=True)
        return {"ok": False, "error": f"Failed to create deployment: {e}"}
    except Exception as e:
        logger.exception("[AdminAgentDeploy] Failed to create deployment")
        return {"ok": False, "error": f"Failed to create deployment: {e}"}

    # ========== GENERATE ENROLLMENT TOKEN ==========
    try:
        enrollment_token = await runtime.agent_manager.generate_enrollment_token(
            agent_name
        )

        # Store token on deployment for later revocation if needed
        deployment = await runtime.deployment_tracker.get(deployment_id)
        if deployment:
            deployment.enrollment_token_str = enrollment_token
    except STORAGE_BOUNDARY_ERRORS as e:
        logger.warning(
            "[AdminAgentDeploy] token generation / deployment persist storage error",
            exc_info=True,
        )
        await runtime.deployment_tracker.update_status(
            deployment_id, "failed", error_message=f"Token generation failed: {e}"
        )
        return {"ok": False, "error": f"Failed to generate enrollment token: {e}"}
    except Exception as e:
        logger.exception("[AdminAgentDeploy] Token generation failed")
        await runtime.deployment_tracker.update_status(
            deployment_id, "failed", error_message=f"Token generation failed: {e}"
        )
        return {"ok": False, "error": f"Failed to generate enrollment token: {e}"}

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
            custom_env=custom_env,
            core_url=custom_core_url,
        )
    )

    logger.info(
        "[AdminAgentDeploy] Deployment started",
        extra={
            "deployment_id": deployment_id,
            "agent_name": agent_name,
            "host": host,
            "credential_id": credential_id,
        },
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
        "next_check": f"poll GET /admin/v1/deployments/{deployment_id}",
    }


async def _execute_deployment(
    runtime: Any,
    deployment_id: str,
    agent_name: str,
    credential_id: str,
    enrollment_token: str,
    host: str,
    custom_env: Dict[str, str],
    core_url: str | None = None,
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

        # ========== SSH DEPLOYMENT ==========
        logger.info(f"[ExecuteDeployment] Starting SSH deployment: {deployment_id}")

        await runtime.deployment_tracker.update_status(
            deployment_id, status="uploading", progress=10
        )

        # Use AgentDeployService to deploy
        from modules.agent.deploy_service import AgentDeployService

        deploy_service = AgentDeployService(runtime)

        try:
            deploy_result = await deploy_service.deploy(
                credential_id=credential_id,
                agent_name=agent_name,
                core_url=core_url,
            )

            logger.info(
                "[ExecuteDeployment] SSH deployment completed",
                extra={
                    "deployment_id": deployment_id,
                    "agent_name": agent_name,
                    "result": deploy_result,
                },
            )
        except (OSError, asyncio.TimeoutError) as e:
            logger.warning(
                "[ExecuteDeployment] SSH deployment IO/timeout: %s", e, exc_info=True
            )
            await runtime.deployment_tracker.update_status(
                deployment_id,
                status="failed",
                error_message=f"SSH deployment failed: {e}",
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
            return
        except Exception as e:
            logger.exception("[ExecuteDeployment] SSH deployment failed")
            await runtime.deployment_tracker.update_status(
                deployment_id,
                status="failed",
                error_message=f"SSH deployment failed: {e}",
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
            return

        await runtime.deployment_tracker.update_status(
            deployment_id,
            status="deployed",
            progress=50,
            install_stdout=deploy_result.get("install_stdout", ""),
            install_stderr=deploy_result.get("install_stderr", ""),
        )

        # ========== WAIT FOR ENROLLMENT ==========
        logger.info(f"[ExecuteDeployment] Waiting for enrollment: {agent_name}")

        await runtime.deployment_tracker.update_status(
            deployment_id, status="deploying", progress=60
        )

        # Now agent should start and try to enroll
        deadline = datetime.now(timezone.utc) + timedelta(seconds=60)  # 60s to enroll
        enrolled_agent_id = None
        poll_count = 0

        while datetime.now(timezone.utc) < deadline:
            # Check if agent is enrolled
            try:
                agents = await runtime.agent_manager.list_enrolled_agents()
                poll_count += 1

                # Log every 5 polls (~10s) to trace enrollment status
                if poll_count <= 3 or poll_count % 5 == 0:
                    enrolled_names = []
                    for _aid in agents:
                        _ident = await runtime.agent_manager.get_agent_identity(_aid)
                        if _ident:
                            enrolled_names.append(_ident.agent_name)
                    logger.warning(
                        f"[ExecuteDeployment] Poll #{poll_count}: looking for {agent_name!r}, "
                        f"enrolled_agents={enrolled_names}"
                    )

                # Try to find our agent
                for agent_id in agents:
                    identity = await runtime.agent_manager.get_agent_identity(agent_id)
                    if identity and identity.agent_name == agent_name:
                        enrolled_agent_id = agent_id
                        break

                if enrolled_agent_id:
                    break
            except STORAGE_BOUNDARY_ERRORS:
                logger.debug(
                    "[ExecuteDeployment] enrollment poll storage error",
                    exc_info=True,
                )
            except Exception:
                logger.warning(
                    "[ExecuteDeployment] Error checking enrollment",
                    exc_info=True,
                )

            await asyncio.sleep(2)

        if not enrolled_agent_id:
            logger.warning(
                f"[ExecuteDeployment] Agent did not enroll within timeout: {agent_name}"
            )
            await runtime.deployment_tracker.update_status(
                deployment_id,
                status="timeout",
                error_message="Agent did not enroll within 60 seconds",
                completed_at=datetime.now(timezone.utc).isoformat(),
            )

            # Cleanup: revoke enrollment token
            try:
                if deployment.enrollment_token_id:
                    await runtime.agent_manager.revoke_enrollment_token(
                        deployment.enrollment_token_id
                    )
            except STORAGE_BOUNDARY_ERRORS:
                logger.debug(
                    "[ExecuteDeployment] revoke enrollment token cleanup storage error",
                    exc_info=True,
                )
            except Exception:
                logger.warning(
                    "[ExecuteDeployment] revoke enrollment token cleanup failed",
                    exc_info=True,
                )

            return

        logger.info(
            "[ExecuteDeployment] Agent enrolled successfully",
            extra={
                "deployment_id": deployment_id,
                "agent_id": enrolled_agent_id,
                "agent_name": agent_name,
            },
        )

        await runtime.deployment_tracker.update_status(
            deployment_id, status="registering", agent_id=enrolled_agent_id, progress=75
        )

        # ========== WAIT FOR HEARTBEAT ==========
        logger.info(
            f"[ExecuteDeployment] Waiting for agent heartbeat: {enrolled_agent_id}"
        )

        deadline = datetime.now(timezone.utc) + timedelta(
            seconds=240
        )  # 240s remaining (300s total - 60s enrollment)
        agent_online = False

        while datetime.now(timezone.utc) < deadline:
            try:
                agent_metadata = await runtime.agent_registry.get_agent(
                    enrolled_agent_id
                )

                # Check last heartbeat
                if (
                    agent_metadata
                    and hasattr(agent_metadata, "last_heartbeat")
                    and agent_metadata.last_heartbeat
                ):
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
                elif agent_metadata and hasattr(agent_metadata, "status"):
                    # Check status field
                    if (
                        agent_metadata.status == "online"
                        or agent_metadata.status == "ready"
                    ):
                        agent_online = True
                        break
            except STORAGE_BOUNDARY_ERRORS:
                logger.debug(
                    "[ExecuteDeployment] heartbeat check storage error",
                    exc_info=True,
                )
            except Exception:
                logger.debug(
                    "[ExecuteDeployment] Error checking heartbeat",
                    exc_info=True,
                )

            await asyncio.sleep(3)

        if not agent_online:
            logger.warning(
                f"[ExecuteDeployment] Agent did not report heartbeat: {enrolled_agent_id}"
            )
            await runtime.deployment_tracker.update_status(
                deployment_id,
                status="timeout",
                agent_id=enrolled_agent_id,
                error_message="Agent did not report heartbeat within timeout",
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
            return

        # ========== SUCCESS ==========
        logger.info(
            "[ExecuteDeployment] Deployment successful",
            extra={
                "deployment_id": deployment_id,
                "agent_id": enrolled_agent_id,
                "agent_name": agent_name,
            },
        )

        await runtime.deployment_tracker.update_status(
            deployment_id,
            status="ready",
            agent_id=enrolled_agent_id,
            progress=100,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )

    except Exception as e:
        # ========== UNEXPECTED FAILURE HANDLING ==========
        logger.exception("[ExecuteDeployment] Unexpected error during deployment")

        try:
            await runtime.deployment_tracker.update_status(
                deployment_id,
                status="failed",
                error_message=str(e),
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
        except STORAGE_BOUNDARY_ERRORS:
            logger.warning(
                "[ExecuteDeployment] update_status after error (storage boundary)",
                exc_info=True,
            )
        except Exception:
            logger.exception(
                "[ExecuteDeployment] Failed to update deployment status after error"
            )


async def admin_agent_get_deployment_status(
    runtime: Any, deployment_id: str
) -> Dict[str, Any]:
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
            return {"ok": False, "error": "deployment_not_found"}

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

        if deployment.install_stdout is not None:
            result["install_stdout"] = deployment.install_stdout
        if deployment.install_stderr is not None:
            result["install_stderr"] = deployment.install_stderr

        return result

    except STORAGE_BOUNDARY_ERRORS as e:
        logger.warning("[AdminAgentGetDeploymentStatus] storage error", exc_info=True)
        return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.exception("[AdminAgentGetDeploymentStatus] Error")
        return {"ok": False, "error": str(e)}


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
        return {"ok": True, **metrics}
    except STORAGE_BOUNDARY_ERRORS as e:
        logger.warning("[AdminAgentGetDeploymentMetrics] storage error", exc_info=True)
        return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.exception("[AdminAgentGetDeploymentMetrics] Error")
        return {"ok": False, "error": str(e)}


async def admin_agent_heartbeat(
    runtime: Any, agent_id: str, body: Optional[Dict[str, Any]] = None
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
            return {"ok": False, "error": "agent_not_found"}

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
                await runtime.agent_registry.update_agent_capabilities(
                    agent_id, body["capabilities"]
                )

        logger.debug(
            "[AdminAgentHeartbeat] Heartbeat received",
            extra={
                "agent_id": agent_id,
                "agent_name": agent.agent_name
                if hasattr(agent, "agent_name")
                else None,
            },
        )

        # Check if there are pending deployments waiting for this agent
        # (this would mark deployment as READY)
        if runtime.deployment_tracker:
            try:
                pending_deployments = await runtime.deployment_tracker.list_deployments(
                    status="registering", limit=100
                )

                for deployment in pending_deployments:
                    if deployment.agent_id == agent_id:
                        # Found deployment waiting for this agent
                        await runtime.deployment_tracker.update_status(
                            deployment.deployment_id,
                            status="ready",
                            progress=100,
                            completed_at=now.isoformat(),
                        )
                        logger.info(
                            "[AdminAgentHeartbeat] Deployment ready via heartbeat",
                            extra={
                                "deployment_id": deployment.deployment_id,
                                "agent_id": agent_id,
                            },
                        )
            except STORAGE_BOUNDARY_ERRORS:
                logger.debug(
                    "[AdminAgentHeartbeat] deployment status update storage error",
                    exc_info=True,
                )
            except Exception:
                logger.debug(
                    "[AdminAgentHeartbeat] Error updating deployment status",
                    exc_info=True,
                )

        return {"ok": True, "ack": True, "server_time": now.isoformat()}

    except STORAGE_BOUNDARY_ERRORS as e:
        logger.warning("[AdminAgentHeartbeat] storage error", exc_info=True)
        return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.exception("[AdminAgentHeartbeat] Error")
        return {"ok": False, "error": str(e)}


# ============================================================================
# TASK 2.2: Agent Binary Download & Checksum
# ============================================================================


def _resolve_binary_path(arch: str) -> Optional["Path"]:
    """
    Resolve agent binary file path from AGENT_BINARY_PATH env var.

    Lookup order:
      1. $AGENT_BINARY_PATH/remote-client-{arch}   (arch-specific)
      2. $AGENT_BINARY_PATH/remote-client           (generic fallback)
      3. $AGENT_BINARY_PATH itself                  (if it points to a file directly)
    """
    import os
    from pathlib import Path

    base = os.environ.get("AGENT_BINARY_PATH", "").strip()
    if not base:
        return None

    base_path = Path(base)

    candidates = [
        base_path / f"remote-client-{arch}",
        base_path / "remote-client",
        base_path,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


async def admin_agent_download_checksum(
    runtime: Any, **query_params: Any
) -> Dict[str, Any]:
    """
    Return SHA256 checksum of agent binary for installer verification.

    Reads AGENT_BINARY_PATH to locate the binary and compute its checksum.

    Query parameters:
      - arch: target architecture string (default: linux-amd64)
    """
    import hashlib

    arch = query_params.get("arch", "linux-amd64")
    binary_path = _resolve_binary_path(arch)
    if binary_path is None:
        logger.warning(
            "[AdminAgentDownloadChecksum] AGENT_BINARY_PATH not set or binary not found"
        )
        return {
            "ok": False,
            "error": "binary_not_found",
            "message": "Agent binary not configured — set AGENT_BINARY_PATH env var",
        }

    try:
        data = binary_path.read_bytes()
        sha256 = hashlib.sha256(data).hexdigest()
        logger.info(f"[AdminAgentDownloadChecksum] sha256={sha256} file={binary_path}")
        return {
            "ok": True,
            "sha256": sha256,
            "size_bytes": len(data),
            "filename": binary_path.name,
            "version": "latest",
            "cached": False,
        }
    except OSError as e:
        logger.warning(
            "[AdminAgentDownloadChecksum] OS error reading binary: %s", e, exc_info=True
        )
        return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.exception("[AdminAgentDownloadChecksum] Error reading binary")
        return {"ok": False, "error": str(e)}


async def admin_agent_download_binary(
    runtime: Any,
    **query_params: Any,
) -> Any:
    """
    Stream agent binary directly to the installer.

    Reads the binary from AGENT_BINARY_PATH and returns a FileResponse so
    the installer can pipe it straight to disk.  No authentication is required
    (the endpoint is marked public) because admin_access_middleware already
    restricts /admin/* to private-network clients.

    Query parameters:
      - arch: target architecture string (default: linux-amd64)
    """
    from fastapi.responses import FileResponse, JSONResponse

    arch = query_params.get("arch", "linux-amd64")
    logger.info(f"[AdminAgentDownloadBinary] requested arch={arch}")

    binary_path = _resolve_binary_path(arch)
    if binary_path is None:
        logger.warning(
            f"[AdminAgentDownloadBinary] Binary not found for arch={arch}. "
            "Set AGENT_BINARY_PATH env var."
        )
        return JSONResponse(
            status_code=404,
            content={
                "ok": False,
                "error": "binary_not_found",
                "message": (
                    f"No binary found for arch={arch}. "
                    "Configure AGENT_BINARY_PATH on the server."
                ),
            },
        )

    logger.info(
        f"[AdminAgentDownloadBinary] Serving {binary_path} ({binary_path.stat().st_size} bytes)"
    )
    return FileResponse(
        path=str(binary_path),
        filename=f"remote-client-{arch}",
        media_type="application/octet-stream",
    )


# ============================================================================
# TASK 1.3: Heartbeat Monitoring & Agent Health
# ============================================================================


async def admin_agent_get_heartbeat_status(
    runtime: Any, agent_id: str
) -> Dict[str, Any]:
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
                last_heartbeat = datetime.fromisoformat(
                    last_heartbeat_str.replace("Z", "+00:00")
                )
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
            "[AdminAgentHeartbeatStatus] Status checked",
            extra={"agent_id": agent_id, "status": status, "age_seconds": age_seconds},
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
            "metrics": metrics,
        }

    except STORAGE_BOUNDARY_ERRORS as e:
        logger.warning("[AdminAgentHeartbeatStatus] storage error", exc_info=True)
        return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.exception("[AdminAgentHeartbeatStatus] Error")
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

        stats = {"online": 0, "offline": 0, "dead": 0, "unknown": 0}

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
                    last_heartbeat = datetime.fromisoformat(
                        last_heartbeat_str.replace("Z", "+00:00")
                    )
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

            agent_statuses.append(
                {
                    "agent_id": getattr(agent, "agent_id", None),
                    "agent_name": getattr(agent, "agent_name", None),
                    "status": status,
                    "age_seconds": age_seconds,
                }
            )

        # Mark dead agents if needed (optional cleanup)
        for dead_agent in dead_agents:
            try:
                agent_id = getattr(dead_agent, "agent_id", None)
                if agent_id:
                    # Mark as deregistered/dead in DB (non-blocking)
                    logger.warning(
                        "[AdminAgentHealthCheck] Agent marked as dead",
                        extra={"agent_id": agent_id},
                    )
                    # Optionally call: await runtime.agent_registry.deregister_agent(agent_id)
            except (AttributeError, TypeError):
                logger.debug(
                    "[AdminAgentHealthCheck] dead agent metadata access failed",
                    exc_info=True,
                )

        logger.info("[AdminAgentHealthCheck] Health check completed", extra=stats)

        return {
            "ok": True,
            "timestamp": now_str,
            "total_agents": len(agents),
            "stats": stats,
            "agents": agent_statuses,
        }

    except STORAGE_BOUNDARY_ERRORS as e:
        logger.warning("[AdminAgentHealthCheck] storage error", exc_info=True)
        return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.exception("[AdminAgentHealthCheck] Error")
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
                last_heartbeat = datetime.fromisoformat(
                    last_heartbeat_str.replace("Z", "+00:00")
                )
                age_seconds = int((now - last_heartbeat).total_seconds())

                # Consider online if < 30 seconds
                if age_seconds < 30:
                    online_agents.append(
                        {
                            "agent_id": getattr(agent, "agent_id", None),
                            "agent_name": getattr(agent, "agent_name", None),
                            "last_heartbeat": last_heartbeat_str,
                            "age_seconds": age_seconds,
                            "capabilities": getattr(agent, "capabilities", []),
                        }
                    )
            except (ValueError, AttributeError):
                pass  # Skip if heartbeat parse fails

        logger.debug(
            "[AdminAgentListOnline] Listed online agents",
            extra={"count": len(online_agents)},
        )

        return {"ok": True, "count": len(online_agents), "agents": online_agents}

    except STORAGE_BOUNDARY_ERRORS as e:
        logger.warning("[AdminAgentListOnline] storage error", exc_info=True)
        return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.exception("[AdminAgentListOnline] Error")
        return {"ok": False, "error": str(e)}


# ============================================================================
# TASK 3.1: Agent Logs API
# ============================================================================


async def admin_agent_submit_logs(
    runtime: Any,
    agent_id: str,
    body: Optional[Dict[str, Any]] = None,
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

    except STORAGE_BOUNDARY_ERRORS as e:
        logger.warning("[AdminAgentGetLogs] storage error", exc_info=True)
        return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.exception("[AdminAgentGetLogs] Error")
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
                    status = (
                        "degraded" if reported not in ("ok", "online") else "online"
                    )
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
                all_deps = await runtime.deployment_tracker.list_deployments(limit=200)
                for dep in all_deps:
                    if dep.agent_id == agent_id:
                        deployment_id = dep.deployment_id
                        break
            except STORAGE_BOUNDARY_ERRORS:
                logger.debug(
                    "[AdminAgentGetStatus] list_deployments storage error",
                    exc_info=True,
                )
            except Exception:
                logger.warning(
                    "[AdminAgentGetStatus] list_deployments failed",
                    exc_info=True,
                )

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

    except STORAGE_BOUNDARY_ERRORS as e:
        logger.warning("[AdminAgentGetStatus] storage error", exc_info=True)
        return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.exception("[AdminAgentGetStatus] Error")
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
                        "[AgentHealthMonitor] High dead agent rate",
                        extra={
                            "dead_count": dead_count,
                            "total": total,
                            "percentage": (dead_count / total) * 100,
                        },
                    )
                else:
                    logger.debug("[AgentHealthMonitor] Health check OK", extra=stats)

        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("[AgentHealthMonitor] Error in health monitoring")
            await asyncio.sleep(60)  # Wait before retry
