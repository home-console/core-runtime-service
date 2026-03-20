"""
Operation handlers for operation types not owned by a domain module.

Device operations (device.set_state, device.mapping.*) — в DevicesModule (modules/devices/operations.py).
Yandex operations (yandex.sync_devices, yandex.check_devices_online) — в плагине yandex_smart_home.
Здесь остаётся только OAuth handler (до переноса в плагин oauth при необходимости).
"""

from typing import Any, Dict


# ============================================================================
# OAuth Operations
# ============================================================================

async def handle_oauth_refresh(params: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handler: oauth.refresh_token
    
    Refreshes OAuth tokens (e.g., Yandex).
    
    Params:
        - service (str): Service name (e.g., "yandex")
    
    Returns:
        - success (bool): Whether refresh succeeded
        - service (str): Service name
        - token_expires_in (int): Token expiration in seconds
    """
    service = params.get("service", "yandex")
    
    runtime = context.get("runtime")
    if not runtime:
        raise RuntimeError("Runtime not available in context")
    
    # Call oauth refresh service
    service_name = f"{service}.refresh_tokens"
    ctx = runtime.kernel_context
    services = ctx.get_service("service_registry")

    result = await services.call(service_name)
    
    return {
        "success": True,
        "service": service,
        "token_expires_in": result.get("token_expires_in"),
        "timestamp": result.get("timestamp"),
    }
