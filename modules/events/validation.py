"""Soft validation middleware for event payloads."""

import logging
from typing import Any

from core.messaging.inmemory import EventBusMiddleware
from modules.events.registry import get_event_validator

logger = logging.getLogger(__name__)
class EventValidationMiddleware(EventBusMiddleware):
    async def before_publish(self, event_type: str, data: dict[str, Any]) -> None:
        # soft validation for event payload (non-blocking)
        validator = get_event_validator(event_type)
        if not validator:
            return

        await validator(data)
