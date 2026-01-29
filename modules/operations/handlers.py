"""
Operation handlers for each operation type.

Handlers execute operation logic and return result dict.
Exceptions are caught by OperationManager and stored as operation.error.
"""

from typing import Any, Dict, Optional
import json


# ============================================================================
# Device Operations
# ============================================================================

async def handle_device_set_state(params: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handler: device.set_state
    
    Params:
        - device_id (str): Device ID
        - state (Dict): New device state
        - delta (bool): If True, merge with current state
    
    Returns:
        - success (bool): Whether state was set
        - old_state (Dict): Previous state
        - new_state (Dict): New state
    """
    device_id = params.get("device_id")
    new_state = params.get("state", {})
    delta = params.get("delta", False)
    
    if not device_id:
        raise ValueError("device_id is required")
    
    runtime = context.get("runtime")
    if not runtime:
        raise RuntimeError("Runtime not available in context")
    
    # Get device state service
    devices_service = runtime.service_registry.get_direct("devices.set_state")
    if not devices_service:
        raise RuntimeError("devices.set_state service not available")
    
    # Get current state for delta
    old_state = {}
    if delta:
        try:
            device_info = await runtime.service_registry.call(
                "devices.get_device",
                device_id=device_id
            )
            old_state = device_info.get("state", {})
        except Exception:
            old_state = {}
    
    # Merge if delta
    if delta and old_state:
        merged_state = {**old_state, **new_state}
    else:
        merged_state = new_state
    
    # Set state
    result = await runtime.service_registry.call(
        "devices.set_state",
        device_id=device_id,
        state=merged_state
    )
    
    return {
        "device_id": device_id,
        "success": True,
        "old_state": old_state,
        "new_state": merged_state,
        "device_response": result,
    }


# ============================================================================
# Yandex Operations
# ============================================================================

async def handle_yandex_sync(params: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handler: yandex.sync
    
    Triggers full sync with Yandex Smart Home.
    
    Params: (empty)
    
    Returns:
        - devices_synced (int): Number of devices synced
        - timestamp (float): Sync timestamp
    """
    runtime = context.get("runtime")
    if not runtime:
        raise RuntimeError("Runtime not available in context")
    
    # Call yandex sync service
    result = await runtime.service_registry.call("yandex.full_sync")
    
    return {
        "success": True,
        "devices_synced": result.get("devices_synced", 0),
        "timestamp": result.get("timestamp"),
        "summary": result.get("summary"),
    }


async def handle_yandex_check_online(params: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handler: yandex.check_devices_online
    
    Checks online status of all devices.
    
    Params: (empty)
    
    Returns:
        - devices_checked (int): Number of devices checked
        - online_count (int): Number of online devices
        - offline_count (int): Number of offline devices
    """
    runtime = context.get("runtime")
    if not runtime:
        raise RuntimeError("Runtime not available in context")
    
    # Get all devices
    devices_list = await runtime.service_registry.call("devices.list")
    devices = devices_list.get("devices", [])
    
    online_count = 0
    offline_count = 0
    
    for device in devices:
        if device.get("state", {}).get("online", False):
            online_count += 1
        else:
            offline_count += 1
    
    return {
        "success": True,
        "devices_checked": len(devices),
        "online_count": online_count,
        "offline_count": offline_count,
    }


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
    result = await runtime.service_registry.call(service_name)
    
    return {
        "success": True,
        "service": service,
        "token_expires_in": result.get("token_expires_in"),
        "timestamp": result.get("timestamp"),
    }


# ============================================================================
# Mapping Operations
# ============================================================================

async def handle_mappings_create(params: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handler: mappings.create
    
    Creates new device mapping.
    
    Params:
        - device_id (str): Device ID
        - yandex_device_id (str): Yandex device ID
        - type (str): Mapping type
    
    Returns:
        - mapping_id (str): Created mapping ID
        - device_id (str): Device ID
        - yandex_device_id (str): Yandex device ID
    """
    device_id = params.get("device_id")
    yandex_device_id = params.get("yandex_device_id")
    mapping_type = params.get("type", "auto")
    
    if not device_id or not yandex_device_id:
        raise ValueError("device_id and yandex_device_id are required")
    
    runtime = context.get("runtime")
    if not runtime:
        raise RuntimeError("Runtime not available in context")
    
    # Call mappings service
    result = await runtime.service_registry.call(
        "mappings.create",
        device_id=device_id,
        yandex_device_id=yandex_device_id,
        mapping_type=mapping_type
    )
    
    return {
        "success": True,
        "mapping_id": result.get("mapping_id"),
        "device_id": device_id,
        "yandex_device_id": yandex_device_id,
    }


async def handle_mappings_delete(params: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handler: mappings.delete
    
    Deletes device mapping.
    
    Params:
        - mapping_id (str): Mapping ID to delete
    
    Returns:
        - success (bool): Whether deletion succeeded
        - mapping_id (str): Deleted mapping ID
    """
    mapping_id = params.get("mapping_id")
    
    if not mapping_id:
        raise ValueError("mapping_id is required")
    
    runtime = context.get("runtime")
    if not runtime:
        raise RuntimeError("Runtime not available in context")
    
    # Call mappings service
    await runtime.service_registry.call(
        "mappings.delete",
        mapping_id=mapping_id
    )
    
    return {
        "success": True,
        "mapping_id": mapping_id,
    }


async def handle_mappings_auto(params: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handler: mappings.auto
    
    Auto-discovers and creates device mappings.
    
    Params: (empty)
    
    Returns:
        - mappings_created (int): Number of mappings created
        - mappings (List[Dict]): List of created mappings
    """
    runtime = context.get("runtime")
    if not runtime:
        raise RuntimeError("Runtime not available in context")
    
    # Call mappings auto-discovery service
    result = await runtime.service_registry.call("mappings.auto_discover")
    
    return {
        "success": True,
        "mappings_created": result.get("mappings_created", 0),
        "mappings": result.get("mappings", []),
    }
