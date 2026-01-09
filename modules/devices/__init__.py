from typing import Callable, Dict, List, Optional

from . import services, handlers


def register_devices(runtime) -> Dict[str, Callable]:
    """
    Register devices domain into CoreRuntime.

    - registers services into `runtime.service_registry`
    - subscribes event handlers to `runtime.event_bus`

    Returns a dict with a `unregister()` callable to undo registration.
    """

    service_names = [
        ("devices.list", services.list_devices),
        ("devices.get", services.get_device),
        ("devices.create", services.create_device),
        ("devices.set_state", services.set_state),
        ("devices.list_external", services.list_external),
        ("devices.create_mapping", services.create_mapping),
        ("devices.list_mappings", services.list_mappings),
        ("devices.delete_mapping", services.delete_mapping),
        ("devices.auto_map_external", services.auto_map_external),
    ]

    registered = []

    for name, func in service_names:
        # Skip services that are already registered (idempotent)
        try:
            if runtime.service_registry.has_service(name):
                continue
        except Exception:
            # If service_registry doesn't implement has_service for some reason,
            # fall back to attempting registration and catching ValueError below.
            pass

        async def _wrapper(*args, _func=func, **kwargs):
            return await _func(runtime, *args, **kwargs)

        try:
            runtime.service_registry.register(name, _wrapper)
            registered.append(name)
        except ValueError:
            # already registered concurrently — skip
            continue

    # subscribe handlers
    async def external_state_wrapper(event_type: str, data: dict) -> None:
        await handlers.handle_external_state(runtime, data)

    async def external_device_wrapper(event_type: str, data: dict) -> None:
        await handlers.handle_external_device_discovered(runtime, data)

    runtime.event_bus.subscribe("external.device_state_reported", external_state_wrapper)
    runtime.event_bus.subscribe("external.device_discovered", external_device_wrapper)

    def unregister():
        # unsubscribe handlers
        try:
            runtime.event_bus.unsubscribe("external.device_state_reported", external_state_wrapper)
        except Exception:
            pass
        try:
            runtime.event_bus.unsubscribe("external.device_discovered", external_device_wrapper)
        except Exception:
            pass

        # unregister services
        for s in registered:
            try:
                runtime.service_registry.unregister(s)
            except Exception:
                pass

    return {"unregister": unregister}
