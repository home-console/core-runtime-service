from plugins.devices_plugin import devices_handlers as handlers


async def on_load(plugin) -> None:
    # Register canonical services (strict model)
    plugin.runtime.service_registry.register("devices.list", plugin.list_devices)
    plugin.runtime.service_registry.register("devices.get", plugin.get_device)
    plugin.runtime.service_registry.register("devices.create", plugin.create_device)
    plugin.runtime.service_registry.register("devices.set_state", plugin.set_state)
    plugin.runtime.service_registry.register("devices.list_external", plugin.list_external)
    plugin.runtime.service_registry.register("devices.create_mapping", plugin.create_mapping)
    plugin.runtime.service_registry.register("devices.list_mappings", plugin.list_mappings)
    plugin.runtime.service_registry.register("devices.delete_mapping", plugin.delete_mapping)
    plugin.runtime.service_registry.register("devices.auto_map_external", plugin.auto_map_external)


async def on_start(plugin) -> None:
    # subscribe to external events via handlers

    async def external_state_wrapper(event_type: str, data: dict) -> None:
        await handlers.handle_external_state(plugin, data)

    async def external_device_wrapper(event_type: str, data: dict) -> None:
        await handlers.handle_external_device_discovered(plugin, data)

    plugin.external_state_handler = external_state_wrapper
    plugin.runtime.event_bus.subscribe(
        "external.device_state_reported",
        plugin.external_state_handler
    )

    plugin.external_device_handler = external_device_wrapper
    plugin.runtime.event_bus.subscribe(
        "external.device_discovered",
        plugin.external_device_handler
    )


async def on_stop(plugin) -> None:
    handler = getattr(plugin, "_external_state_handler", None)
    if handler:
        plugin.runtime.event_bus.unsubscribe(
            "external.device_state_reported",
            handler
        )

    handler = getattr(plugin, "_external_device_handler", None)
    if handler:
        plugin.runtime.event_bus.unsubscribe(
            "external.device_discovered",
            handler
        )


async def on_unload(plugin) -> None:
    services = [
        "devices.list",
        "devices.get",
        "devices.create",
        "devices.set_state",
        "devices.list_external",
        "devices.create_mapping",
        "devices.list_mappings",
        "devices.delete_mapping",
        "devices.auto_map_external",
    ]

    for service in services:
        plugin.runtime.service_registry.unregister(service)

    plugin.runtime = None
