from typing import Any, Callable

OperationFactory = Callable[[dict[str, Any]], dict[str, Any]]

_registry: dict[str, list[OperationFactory]] = {}


def register_event_handler(event_type: str, handler: OperationFactory):
    _registry.setdefault(event_type, []).append(handler)


def get_event_handlers(event_type: str):
    return _registry.get(event_type, [])