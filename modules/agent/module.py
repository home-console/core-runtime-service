"""Agent Control Plane Module."""

import asyncio
import logging
import os
from typing import Any

from core.http.models import EndpointAuthConfig, HttpEndpoint
from core.runtime.runtime_module import RuntimeModule

try:
    from modules.security import SecretStore
    from modules.security.secret_store_adapter import SecretStoreStorageAdapter
except ImportError:
    SecretStore = None  # type: ignore[misc, assignment]
    SecretStoreStorageAdapter = None  # type: ignore[misc, assignment]

from modules.agent.services import (
    admin_agent_check_agents_health,
    admin_agent_create_enrollment_token,
    admin_agent_deploy,
    admin_agent_deregister_agent,
    admin_agent_download_binary,
    admin_agent_download_checksum,
    admin_agent_enroll_agent,
    admin_agent_generate_bootstrap_token,
    admin_agent_get_agent,
    admin_agent_get_deployment_metrics,
    admin_agent_get_deployment_status,
    admin_agent_get_heartbeat_status,
    admin_agent_get_logs,
    admin_agent_get_status,
    admin_agent_heartbeat,
    admin_agent_list_agents,
    admin_agent_list_agents_providing_capability,
    admin_agent_list_online_agents,
    admin_agent_submit_logs,
)
from modules.agent.domain import (
    AgentEnrollmentManager,
    AgentRegistry,
    DeploymentTracker,
    MTLSCertificateAuthority,
)

logger = logging.getLogger(__name__)


from modules.security.master_key import resolve_master_key_passphrase as _resolve_master_key_for_agent_module


class AgentControlPlaneModule(RuntimeModule):
    """
    Agent Control Plane Module.

    Manages:
    - Agent enrollment with tokens
    - Agent identity & mTLS certificates
    - Agent registry & status tracking
    - Agent capability routing
    """

    @property
    def name(self) -> str:
        """Unique module name."""
        return "agent_control_plane"

    async def register(self) -> None:
        """
        Register Agent Control Plane with CoreRuntime.

        - Initialize SecretStore
        - Initialize AgentEnrollmentManager
        - Initialize AgentRegistry
        - Initialize MTLSCertificateAuthority
        - Register HTTP endpoints
        """
        if self.runtime is None:
            raise RuntimeError("AgentModule requires full runtime (not RuntimeContext)")

        # Use SecretStore from runtime if already set (main/bootstrap), otherwise create
        secret_store = getattr(self.runtime, "secret_store", None)
        if secret_store is None:
            # В dual mode обязательно vault через SecureStorage (get_vault), иначе root hash не обновляется
            manager = getattr(self.runtime, "storage_manager", None)
            if manager is not None and getattr(manager, "is_dual_mode", False):
                backend = manager.get_vault()
            else:
                storage = (
                    self.context.storage
                    if hasattr(self, "context") and self.context
                    else self.context.storage
                )
                backend = getattr(
                    getattr(storage, "_storage", storage), "_adapter", None
                )
            if backend is None:
                raise RuntimeError(
                    "Agent module: cannot get storage backend for SecretStore"
                )
            wrapper = SecretStoreStorageAdapter(backend)
            secret_store = SecretStore(wrapper)
            try:
                passphrase = _resolve_master_key_for_agent_module()
            except RuntimeError:
                cfg = getattr(self.runtime, "_config", None)
                env = str(getattr(cfg, "env", "") or "").lower()
                is_pytest = bool(os.getenv("PYTEST_CURRENT_TEST"))
                if is_pytest or env in {"test", "testing"}:
                    passphrase = "test-master-key"
                    logger.warning(
                        "[agent] RUNTIME_MASTER_KEY missing; using test key (env=%s pytest=%s)",
                        env,
                        is_pytest,
                    )
                else:
                    raise
            try:
                await secret_store.open_with_passphrase(passphrase)
            except RuntimeError:
                # Salt doesn't exist yet — first-time initialization
                await secret_store.initialize(passphrase)
            except Exception as e:
                # Decryption failed (e.g., InvalidTag) — vault was recreated or passphrase changed
                logger.warning(
                    "[agent] Cannot decrypt stored credentials (%s). Resetting agent CA.",
                    e
                )
                # Clear old encrypted data and reinitialize
                try:
                    await secret_store.delete("agent:ca:private_key")
                    await secret_store.delete("agent:ca:certificate")
                except Exception:
                    pass  # Keys may not exist yet
                await secret_store.initialize(passphrase)
            self.runtime.secret_store = secret_store

        # Initialize mTLS Certificate Authority
        # Check if CA certificate already exists in storage
        ca_exists = await secret_store.exists("agent:ca:private_key")

        if ca_exists:
            # Load existing CA from storage
            ca_private_pem = await secret_store.get("agent:ca:private_key")
            ca_cert_pem = await secret_store.get("agent:ca:certificate")
            if ca_private_pem is None or ca_cert_pem is None:
                raise RuntimeError("Agent CA materials are missing from SecretStore")
            mtls_ca = MTLSCertificateAuthority(ca_private_pem, ca_cert_pem)
        else:
            # Generate new CA
            ca_private_pem, ca_cert_pem = (
                MTLSCertificateAuthority.generate_ca_certificate()
            )

            # Store CA in SecretStore
            await secret_store.put("agent:ca:private_key", ca_private_pem)
            await secret_store.put("agent:ca:certificate", ca_cert_pem)

            mtls_ca = MTLSCertificateAuthority(ca_private_pem, ca_cert_pem)

        # Initialize AgentEnrollmentManager
        agent_manager = AgentEnrollmentManager(secret_store)

        # Initialize AgentRegistry
        agent_registry = AgentRegistry()

        # Initialize DeploymentTracker (in-memory with optional DB persistence)
        deployment_tracker = DeploymentTracker(
            db_service=getattr(self.runtime, "db", None)
        )

        # Store in CoreRuntime (secret_store — для credentials и inspector в debug)
        self.runtime.secret_store = secret_store
        self.runtime.agent_manager = agent_manager
        self.runtime.agent_registry = agent_registry
        self.runtime.mtls_ca = mtls_ca
        self.runtime.deployment_tracker = deployment_tracker

        # Initialize AgentLogStore (TASK 3.1)
        from modules.agent.domain import AgentLogStore

        self.runtime.agent_log_store = AgentLogStore()

        # Register admin.* agent services with a unified helper.
        # Admin access is required for all of these endpoints.
        async def _reg(service_name: str, fn: Any) -> None:
            await self.register_runtime_service(
                service_name,
                fn,
                admin_only=True,
                resource="agent",
            )

        await _reg("admin.agent.create_enrollment_token", admin_agent_create_enrollment_token)
        await _reg("admin.agent.generate_bootstrap_token", admin_agent_generate_bootstrap_token)
        await _reg("admin.agent.enroll_agent", admin_agent_enroll_agent)
        await _reg("admin.agent.list_agents", admin_agent_list_agents)
        await _reg("admin.agent.get_agent", admin_agent_get_agent)
        await _reg("admin.agent.deregister_agent", admin_agent_deregister_agent)
        await _reg(
            "admin.agent.list_agents_providing_capability",
            admin_agent_list_agents_providing_capability,
        )

        # ==== Deployment Services (TASK 1.1) ====
        await _reg("admin.agent.deploy", admin_agent_deploy)
        await _reg("admin.agent.get_deployment_status", admin_agent_get_deployment_status)
        await _reg("admin.agent.get_deployment_metrics", admin_agent_get_deployment_metrics)
        await _reg("admin.agent.heartbeat", admin_agent_heartbeat)

        # ==== Heartbeat Monitoring Services (TASK 1.3) ====
        await _reg("admin.agent.get_heartbeat_status", admin_agent_get_heartbeat_status)
        await _reg("admin.agent.check_agents_health", admin_agent_check_agents_health)
        await _reg("admin.agent.list_online_agents", admin_agent_list_online_agents)

        # ==== Download Services (TASK 2.2) ====
        await _reg("admin.agent.download_checksum", admin_agent_download_checksum)
        await _reg("admin.agent.download_binary", admin_agent_download_binary)

        # ==== Logs + Status Services (TASK 3.1 / 3.2) ====
        await _reg("admin.agent.submit_logs", admin_agent_submit_logs)
        await _reg("admin.agent.get_logs", admin_agent_get_logs)
        await _reg("admin.agent.get_status", admin_agent_get_status)

        # Register HTTP endpoints for Agent Control Plane
        _admin_read = EndpointAuthConfig(required_scopes=["admin.read"])
        _admin_write = EndpointAuthConfig(required_scopes=["admin.write"])

        # Enrollment endpoints
        self.context.http.register(
            HttpEndpoint(
                method="POST",
                path="/api/v1/admin/agents/enrollment-token",
                service="admin.agent.create_enrollment_token",
                description="Create enrollment token for new agent",
                auth_config=_admin_write,
            )
        )

        # Bootstrap token for installer / manual agent installation (HMAC-signed, TTL 10m)
        self.context.http.register(
            HttpEndpoint(
                method="POST",
                path="/api/v1/admin/agents/bootstrap-token",
                service="admin.agent.generate_bootstrap_token",
                description="Generate one-time bootstrap enrollment token for installer",
                auth_config=_admin_write,
            )
        )

        self.context.http.register(
            HttpEndpoint(
                method="POST",
                path="/api/v1/admin/agents/enroll",
                service="admin.agent.enroll_agent",
                description="Enroll agent with enrollment token",
                auth_config=_admin_write,
            )
        )

        # Agent registry endpoints
        self.context.http.register(
            HttpEndpoint(
                method="GET",
                path="/api/v1/admin/agents",
                service="admin.agent.list_agents",
                description="List all registered agents",
                auth_config=_admin_read,
            )
        )

        self.context.http.register(
            HttpEndpoint(
                method="GET",
                path="/api/v1/admin/agents/{agent_id}",
                service="admin.agent.get_agent",
                description="Get agent details",
                auth_config=_admin_read,
            )
        )

        self.context.http.register(
            HttpEndpoint(
                method="POST",
                path="/api/v1/admin/agents/{agent_id}/deregister",
                service="admin.agent.deregister_agent",
                description="Deregister agent",
                auth_config=_admin_write,
            )
        )

        # ==== Deployment Endpoints (TASK 1.1) ====
        self.context.http.register(
            HttpEndpoint(
                method="POST",
                path="/api/v1/admin/agents/deploy",
                service="admin.agent.deploy",
                description="Deploy agent to remote host via SSH",
                auth_config=_admin_write,
            )
        )

        self.context.http.register(
            HttpEndpoint(
                method="GET",
                path="/api/v1/admin/deployments/{deployment_id}",
                service="admin.agent.get_deployment_status",
                description="Get agent deployment status",
                auth_config=_admin_read,
            )
        )

        self.context.http.register(
            HttpEndpoint(
                method="GET",
                path="/api/v1/admin/deployments",
                service="admin.agent.get_deployment_metrics",
                description="Get deployment metrics and statistics",
                auth_config=_admin_read,
            )
        )

        self.context.http.register(
            HttpEndpoint(
                method="POST",
                path="/api/v1/admin/agents/{agent_id}/heartbeat",
                service="admin.agent.heartbeat",
                description="Receive heartbeat from agent",
                auth_config=_admin_write,
            )
        )

        self.context.http.register(
            HttpEndpoint(
                method="GET",
                path="/api/v1/admin/agents/{agent_id}/heartbeat",
                service="admin.agent.get_heartbeat_status",
                description="Get heartbeat status for specific agent",
                auth_config=_admin_read,
            )
        )

        self.context.http.register(
            HttpEndpoint(
                method="GET",
                path="/api/v1/admin/agents/health/check",
                service="admin.agent.check_agents_health",
                description="Check health of all agents",
                auth_config=EndpointAuthConfig(public=True),
            )
        )

        self.context.http.register(
            HttpEndpoint(
                method="GET",
                path="/api/v1/admin/agents/online",
                service="admin.agent.list_online_agents",
                description="List all currently online agents",
                auth_config=_admin_read,
            )
        )

        # Download endpoints (TASK 2.2)
        # Public: installer runs unauthenticated; admin_access_middleware already
        # restricts these paths to private-network clients only.
        _public = EndpointAuthConfig(public=True)
        self.context.http.register(
            HttpEndpoint(
                method="GET",
                path="/api/v1/media/checksum",
                service="admin.agent.download_checksum",
                description="Get SHA256 checksum of agent binary",
                auth_config=_public,
            )
        )

        self.context.http.register(
            HttpEndpoint(
                method="GET",
                path="/api/v1/media/download/binary",
                service="admin.agent.download_binary",
                description="Stream agent binary to installer",
                auth_config=_public,
            )
        )

        # Capability routing endpoints
        self.context.http.register(
            HttpEndpoint(
                method="GET",
                path="/api/v1/admin/agents/capabilities/{capability_id}",
                service="admin.agent.list_agents_providing_capability",
                description="List agents providing capability",
                auth_config=_admin_read,
            )
        )

        # TASK 3.1: Agent Logs API
        self.context.http.register(
            HttpEndpoint(
                method="POST",
                path="/api/v1/admin/agents/{agent_id}/logs",
                service="admin.agent.submit_logs",
                description="Agent pushes log entries to Core",
                auth_config=_admin_write,
            )
        )

        self.context.http.register(
            HttpEndpoint(
                method="GET",
                path="/api/v1/admin/agents/{agent_id}/logs",
                service="admin.agent.get_logs",
                description="Get stored logs for agent",
                auth_config=_admin_read,
            )
        )

        # TASK 3.2: Agent Status endpoint
        self.context.http.register(
            HttpEndpoint(
                method="GET",
                path="/api/v1/admin/agents/{agent_id}/status",
                service="admin.agent.get_status",
                description="Get real-time status of agent",
                auth_config=_admin_read,
            )
        )

    async def start(self) -> None:
        """Start Agent Control Plane module."""
        # TASK 1.3: Start background health monitoring task
        from modules.agent.services import _monitor_agent_health_background

        if self.runtime:
            asyncio.create_task(_monitor_agent_health_background(self.runtime))
            logger.info("✅ Agent health monitoring background task started")

    async def stop(self) -> None:
        """Stop Agent Control Plane module."""
        # Cleanup if needed
        # For now, just log completion
        pass
