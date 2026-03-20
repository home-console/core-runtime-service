import logging
from typing import Any

from modules.events.registry import define_event
from modules.events.schema import validate_schema

logger = logging.getLogger(__name__)


device_state_schema = {
    "external_id": str,
    "state": dict,
    "source": ("optional", ("ws", "rest", "optimistic", "polling", "replay")),
}


device_discovered_schema = {
    "external_id": str,
    "provider": str,
    "capabilities": ("optional", dict),
}


async def validate_external_device_state(data: dict[str, Any]) -> None:
    try:
        validate_schema(device_state_schema, data)
    except Exception as e:
        logger.warning(
            "EventBus: invalid payload for 'external.device_state_reported': %s",
            e,
        )


async def validate_device_discovered(data: dict[str, Any]) -> None:
    try:
        validate_schema(device_discovered_schema, data)
    except Exception as e:
        logger.warning(
            "EventBus: invalid payload for 'external.device_discovered': %s",
            e,
        )


define_event(
    "external.device_state_reported",
    schema=device_state_schema,
    validator=validate_external_device_state,
)

define_event(
    "external.device_discovered",
    schema=device_discovered_schema,
    validator=validate_device_discovered,
)
