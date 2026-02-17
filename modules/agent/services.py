"""Step 15: Agent Control Plane Services."""

from typing import Any, Dict, List, Optional
from datetime import datetime, timezone


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
