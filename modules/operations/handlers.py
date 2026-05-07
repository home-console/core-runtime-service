"""
Operation handlers for operation types not owned by a domain module.

Device operations (device.set_state, device.mapping.*) — в DevicesModule (modules/devices/operations.py).
Integration-specific operations are owned by corresponding plugins.
Здесь остаётся только OAuth handler (до переноса в плагин oauth при необходимости).
"""

from typing import Any, Dict


# ============================================================================
# OAuth Operations
# ============================================================================

async def handle_oauth_refresh(params: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handler: oauth.refresh_token
    
    Refreshes OAuth tokens for a given provider.
    
    Params:
        - service (str): Provider service prefix (e.g., "oauth_provider")
    
    Returns:
        - success (bool): Whether refresh succeeded
        - service (str): Service name
        - token_expires_in (int): Token expiration in seconds
    """
    service = params.get("service", "oauth_provider")
    
    runtime = context.get("runtime")
    if not runtime:
        raise RuntimeError("Runtime not available in context")
    
    # Call oauth refresh service
    service_name = f"{service}.refresh_tokens"
    result = await runtime.service_registry.call(service_name)
    
    return {
        "success": True,
        "service": service,
        "token_expires_in": result.get("token_expires_in"),
        "timestamp": result.get("timestamp"),
    }
