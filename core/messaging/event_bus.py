from modules.event_bus.inmemory import (
    EventBusMiddleware,
    InMemoryEventBus,
    TypedEventHandler as EventHandler,
)

EventBus = InMemoryEventBus

__all__ = ["EventBus", "InMemoryEventBus", "EventBusMiddleware", "EventHandler"]
