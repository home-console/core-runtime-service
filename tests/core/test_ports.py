"""Тест соответствия реализаций Protocol-интерфейсам."""

from core.messaging import InMemoryEventBus
from core.ports import IEventBus, IServiceRegistry
from core.service.registry import ServiceRegistry


def test_inmemory_event_bus_implements_interface():
    """InMemoryEventBus должен соответствовать IEventBus Protocol."""
    assert isinstance(InMemoryEventBus(), IEventBus)


def test_service_registry_implements_interface():
    """ServiceRegistry должен соответствовать IServiceRegistry Protocol."""
    assert isinstance(ServiceRegistry(), IServiceRegistry)

