"""Step 15: Agent Control Plane Module."""

import os
from datetime import datetime, timezone
from core.runtime_module import RuntimeModule
from core.http_registry import HttpEndpoint

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
    admin_agent_list_agents,
    admin_agent_get_agent,
    admin_agent_deregister_agent,
    admin_agent_list_agents_providing_capability,
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
        # Get or create SecretStore
        # For now, we use a simple in-memory or file-based secret store
        # In production, this would be initialized with a secure passphrase
        secret_store = SecretStore(self.runtime.storage._adapter)
        
        # Initialize SecretStore with a passphrase
        # In production, this should come from environment or secure input
        passphrase = os.getenv("AGENT_SECRET_STORE_PASSPHRASE", "default-dev-passphrase")
        try:
            await secret_store.initialize(passphrase)
        except RuntimeError:
            # Already initialized, which is fine
            pass
        
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
        
        # Store in CoreRuntime
        self.runtime.agent_manager = agent_manager
        self.runtime.agent_registry = agent_registry
        self.runtime.mtls_ca = mtls_ca
        
        # Register services with service registry
        await self.runtime.service_registry.register(
            "admin.agent.create_enrollment_token",
            admin_agent_create_enrollment_token,
        )
        await self.runtime.service_registry.register(
            "admin.agent.enroll_agent",
            admin_agent_enroll_agent,
        )
        await self.runtime.service_registry.register(
            "admin.agent.list_agents",
            admin_agent_list_agents,
        )
        await self.runtime.service_registry.register(
            "admin.agent.get_agent",
            admin_agent_get_agent,
        )
        await self.runtime.service_registry.register(
            "admin.agent.deregister_agent",
            admin_agent_deregister_agent,
        )
        await self.runtime.service_registry.register(
            "admin.agent.list_agents_providing_capability",
            admin_agent_list_agents_providing_capability,
        )
        
        # Register HTTP endpoints for Agent Control Plane
        # Enrollment endpoints
        self.context.http.register(HttpEndpoint(
            method="POST",
            path="/admin/v1/agents/enrollment-token",
            service="admin.agent.create_enrollment_token",
            description="Create enrollment token for new agent"
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
        
        # Capability routing endpoints
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/agents/capabilities/{capability_id}",
            service="admin.agent.list_agents_providing_capability",
            description="List agents providing capability"
        ))

    async def start(self) -> None:
        """Start Agent Control Plane module."""
        # Nothing to do for startup
        # Agent manager and registry are initialized in register()
        pass

    async def stop(self) -> None:
        """Stop Agent Control Plane module."""
        # Cleanup if needed
        # For now, just log completion
        pass
