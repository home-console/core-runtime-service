from typing import Callable, Dict, Any, Awaitable

Validator = Callable[[dict[str, Any]], Awaitable[None]]

_registry: Dict[str, Validator] = {}


def register_event_validator(event_type: str, validator: Validator) -> None:
    _registry[event_type] = validator


def define_event(
    event_type: str,
    *,
    schema: dict,
    validator: Validator,
) -> None:
    register_event_validator(event_type, validator)


def get_event_validator(event_type: str) -> Validator | None:
    return _registry.get(event_type)