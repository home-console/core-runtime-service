"""
Admin integrations services.

Moved from AdminModule for architectural clarity.
Behavior is unchanged.
"""
from typing import Any, Dict, List
import logging
logger = logging.getLogger(__name__)


async def admin_v1_integrations(runtime: Any) -> List[Dict[str, Any]]:
    """Return list of registered integrations."""
    integrations = runtime.integrations.list()
    result = []
    for integration in integrations:
        plugin_state = await runtime.plugin_manager.get_plugin_state(integration.plugin_name)
        state_val = None
        try:
            state_val = getattr(plugin_state, "value", str(plugin_state)) if plugin_state else None
        except Exception:
            logger.debug("integrations.admin_v1_integrations: error (using fallback value)", exc_info=True)
            state_val = str(plugin_state) if plugin_state else None

        result.append({
            "id": integration.id,
            "state": state_val or "unknown",
            "name": integration.name,
            "plugin_name": integration.plugin_name,
            "message": integration.description,
            "metadata": {
                "type": getattr(integration, "type", "integration"),
                "flags": [flag.value for flag in integration.flags],
                "plugin_state": state_val,
                "plugin_loaded": state_val in ("loaded", "started") if state_val else False,
                "plugin_started": state_val == "started" if state_val else False,
            },
        })
    return result
