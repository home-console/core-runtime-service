"""Step 15: Agent Control Plane Module."""

import asyncio
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
from core.runtime_module import RuntimeModule
from core.http_registry import HttpEndpoint
from core.agents.deployment_tracker import DeploymentTracker

try:
    from core.security import SecretStore
except ImportError:
    SecretStore = None  # type: ignore[misc, assignment]

from core.agent.enrollment import AgentEnrollmentManager
from core.agent.registry import AgentRegistry
from core.agent.tls import MTLSCertificateAuthority
from modules.agent.services import (
    admin_agent_create_enrollment_token,
    admin_agent_enroll_agent,
    admin_agent_generate_bootstrap_token,
    admin_agent_list_agents,
    admin_agent_get_agent,
    admin_agent_deregister_agent,
    admin_agent_list_agents_providing_capability,
    admin_agent_deploy,
    admin_agent_get_deployment_status,
    admin_agent_get_deployment_metrics,
    admin_agent_heartbeat,
    admin_agent_get_heartbeat_status,
    admin_agent_check_agents_health,
    admin_agent_list_online_agents,
    admin_agent_download_checksum,
    admin_agent_download_binary,
    admin_agent_submit_logs,
    admin_agent_get_logs,
    admin_agent_get_status,
)


class AgentControlPlaneModule(RuntimeModule):
    """
    Step 15: Agent Control Plane Module.
    
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
        if SecretStore is None:
            raise RuntimeError(
                "Agent module requires SecretStore from core.security; "
                "ensure core.security.secret_store is available (e.g. cryptography package)."
            )
        # Use SecretStore from runtime if already set (main/bootstrap), otherwise create
        secret_store = getattr(self.runtime, "secret_store", None)
        if secret_store is None:
            from core.security.secret_store_adapter import SecretStoreStorageAdapter
            # В dual mode обязательно vault через SecureStorage (get_vault), иначе root hash не обновляется
            manager = getattr(self.runtime, "storage_manager", None)
            if manager is not None and getattr(manager, "is_dual_mode", False):
                backend = manager.get_vault()
            else:
                storage = self.context.storage if hasattr(self, "context") and self.context else self.runtime.storage
                backend = getattr(getattr(storage, "_storage", storage), "_adapter", None)
            if backend is None:
                raise RuntimeError("Agent module: cannot get storage backend for SecretStore")
            wrapper = SecretStoreStorageAdapter(backend)
            secret_store = SecretStore(wrapper)
            passphrase = os.getenv("AGENT_SECRET_STORE_PASSPHRASE", "default-dev-passphrase")
            try:
                await secret_store.initialize(passphrase)
            except RuntimeError:
                await secret_store.open_with_passphrase(passphrase)
            self.runtime.secret_store = secret_store

        # Initialize mTLS Certificate Authority
        # Check if CA certificate already exists in storage
        ca_exists = await secret_store.exists("agent:ca:private_key")
        
        if ca_exists:
            # Load existing CA from storage
            ca_private_pem = await secret_store.get("agent:ca:private_key")
            ca_cert_pem = await secret_store.get("agent:ca:certificate")
            mtls_ca = MTLSCertificateAuthority(ca_private_pem, ca_cert_pem)
        else:
            # Generate new CA
            ca_private_pem, ca_cert_pem = MTLSCertificateAuthority.generate_ca_certificate()
            
            # Store CA in SecretStore
            await secret_store.put("agent:ca:private_key", ca_private_pem)
            await secret_store.put("agent:ca:certificate", ca_cert_pem)
            
            mtls_ca = MTLSCertificateAuthority(ca_private_pem, ca_cert_pem)
        
        # Initialize AgentEnrollmentManager
        agent_manager = AgentEnrollmentManager(secret_store)
        
        # Initialize AgentRegistry
        agent_registry = AgentRegistry()
        
        # Initialize DeploymentTracker (in-memory with optional DB persistence)
        deployment_tracker = DeploymentTracker(db_service=getattr(self.runtime, "db", None))
        
        # Store in CoreRuntime (secret_store — для credentials и inspector в debug)
        self.runtime.secret_store = secret_store
        self.runtime.agent_manager = agent_manager
        self.runtime.agent_registry = agent_registry
        self.runtime.mtls_ca = mtls_ca
        self.runtime.deployment_tracker = deployment_tracker

        # Initialize AgentLogStore (TASK 3.1)
        from core.agents.log_store import AgentLogStore
        self.runtime.agent_log_store = AgentLogStore()

        # Обёртка для admin-хендлеров, которым нужен runtime первым аргументом
        def wrap_agent(fn):
            return lambda *args, **kw: fn(self.runtime, *args, **kw)
        
        # Register services with service registry
        services = self.context.services if hasattr(self, "context") and self.context else self.runtime.service_registry
        await services.register(
            "admin.agent.create_enrollment_token",
            wrap_agent(admin_agent_create_enrollment_token),
        )
        await services.register(
            "admin.agent.generate_bootstrap_token",
            wrap_agent(admin_agent_generate_bootstrap_token),
        )
        await services.register(
            "admin.agent.enroll_agent",
            wrap_agent(admin_agent_enroll_agent),
        )
        await services.register(
            "admin.agent.list_agents",
            wrap_agent(admin_agent_list_agents),
        )
        await services.register(
            "admin.agent.get_agent",
            wrap_agent(admin_agent_get_agent),
        )
        await services.register(
            "admin.agent.deregister_agent",
            wrap_agent(admin_agent_deregister_agent),
        )
        await services.register(
            "admin.agent.list_agents_providing_capability",
            wrap_agent(admin_agent_list_agents_providing_capability),
        )
        
        # ==== Deployment Services (TASK 1.1) ====
        await services.register(
            "admin.agent.deploy",
            wrap_agent(admin_agent_deploy),
        )
        await services.register(
            "admin.agent.get_deployment_status",
            wrap_agent(admin_agent_get_deployment_status),
        )
        await services.register(
            "admin.agent.get_deployment_metrics",
            wrap_agent(admin_agent_get_deployment_metrics),
        )
        await services.register(
            "admin.agent.heartbeat",
            wrap_agent(admin_agent_heartbeat),
        )
        
        # ==== Heartbeat Monitoring Services (TASK 1.3) ====
        await services.register(
            "admin.agent.get_heartbeat_status",
            wrap_agent(admin_agent_get_heartbeat_status),
        )
        await services.register(
            "admin.agent.check_agents_health",
            wrap_agent(admin_agent_check_agents_health),
        )
        await services.register(
            "admin.agent.list_online_agents",
            wrap_agent(admin_agent_list_online_agents),
        )
        
        # ==== Download Services (TASK 2.2) ====
        await services.register(
            "admin.agent.download_checksum",
            wrap_agent(admin_agent_download_checksum),
        )
        await services.register(
            "admin.agent.download_binary",
            wrap_agent(admin_agent_download_binary),
        )

        # ==== Logs + Status Services (TASK 3.1 / 3.2) ====
        await services.register(
            "admin.agent.submit_logs",
            wrap_agent(admin_agent_submit_logs),
        )
        await services.register(
            "admin.agent.get_logs",
            wrap_agent(admin_agent_get_logs),
        )
        await services.register(
            "admin.agent.get_status",
            wrap_agent(admin_agent_get_status),
        )
        
        # Register HTTP endpoints for Agent Control Plane
        # Enrollment endpoints
        self.context.http.register(HttpEndpoint(
            method="POST",
            path="/admin/v1/agents/enrollment-token",
            service="admin.agent.create_enrollment_token",
            description="Create enrollment token for new agent"
        ))

        # Bootstrap token for installer / manual agent installation (HMAC-signed, TTL 10m)
        self.context.http.register(HttpEndpoint(
            method="POST",
            path="/admin/v1/agents/bootstrap-token",
            service="admin.agent.generate_bootstrap_token",
            description="Generate one-time bootstrap enrollment token for installer"
        ))
        
        self.context.http.register(HttpEndpoint(
            method="POST",
            path="/admin/v1/agents/enroll",
            service="admin.agent.enroll_agent",
            description="Enroll agent with enrollment token"
        ))
        
        # Agent registry endpoints
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/agents",
            service="admin.agent.list_agents",
            description="List all registered agents"
        ))
        
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/agents/{agent_id}",
            service="admin.agent.get_agent",
            description="Get agent details"
        ))
        
        self.context.http.register(HttpEndpoint(
            method="POST",
            path="/admin/v1/agents/{agent_id}/deregister",
            service="admin.agent.deregister_agent",
            description="Deregister agent"
        ))
        
        # ==== Deployment Endpoints (TASK 1.1) ====
        self.context.http.register(HttpEndpoint(
            method="POST",
            path="/admin/v1/agents/deploy",
            service="admin.agent.deploy",
            description="Deploy agent to remote host via SSH"
        ))
        
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/deployments/{deployment_id}",
            service="admin.agent.get_deployment_status",
            description="Get agent deployment status"
        ))
        
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/deployments",
            service="admin.agent.get_deployment_metrics",
            description="Get deployment metrics and statistics"
        ))
        
        self.context.http.register(HttpEndpoint(
            method="POST",
            path="/admin/v1/agents/{agent_id}/heartbeat",
            service="admin.agent.heartbeat",
            description="Receive heartbeat from agent"
        ))
        
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/agents/{agent_id}/heartbeat",
            service="admin.agent.get_heartbeat_status",
            description="Get heartbeat status for specific agent"
        ))
        
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/agents/health/check",
            service="admin.agent.check_agents_health",
            description="Check health of all agents"
        ))
        
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/agents/online",
            service="admin.agent.list_online_agents",
            description="List all currently online agents"
        ))
        
        # Download endpoints (TASK 2.2)
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/agents/download/checksum",
            service="admin.agent.download_checksum",
            description="Get SHA256 checksum of agent binary"
        ))
        
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/agents/download/binary",
            service="admin.agent.download_binary",
            description="Get agent binary download metadata and URL"
        ))
        
        # Capability routing endpoints
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/agents/capabilities/{capability_id}",
            service="admin.agent.list_agents_providing_capability",
            description="List agents providing capability"
        ))

        # TASK 3.1: Agent Logs API
        self.context.http.register(HttpEndpoint(
            method="POST",
            path="/admin/v1/agents/{agent_id}/logs",
            service="admin.agent.submit_logs",
            description="Agent pushes log entries to Core"
        ))

        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/agents/{agent_id}/logs",
            service="admin.agent.get_logs",
            description="Get stored logs for agent"
        ))

        # TASK 3.2: Agent Status endpoint
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/agents/{agent_id}/status",
            service="admin.agent.get_status",
            description="Get real-time status of agent"
        ))

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
