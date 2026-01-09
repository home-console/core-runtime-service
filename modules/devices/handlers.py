import copy


async def handle_external_device_discovered(runtime, data: dict) -> None:
    external_id = data.get("external_id")
    if not external_id:
        return

    await runtime.storage.set("devices_external", external_id, data)


async def handle_external_state(runtime, data: dict) -> None:
    external_id = data.get("external_id")
    reported_state = data.get("state")

    if not external_id or reported_state is None:
        return

    internal_id = await runtime.storage.get("devices_mappings", external_id)

    if not internal_id:
        return

    device = await runtime.storage.get("devices", internal_id)

    if device is None:
        return

    old_state = device.get("state", {})

    if not isinstance(old_state, dict) or \
        not all(k in old_state for k in ["desired", "reported", "pending"]):
            await runtime.service_registry.call(
                "logger.log",
                level="warning",
                message=f"Invalid device state format: {internal_id}",
                plugin="devices_module",
                context={"state": old_state}
            )
            return

    if not isinstance(old_state["desired"], dict) or \
       not isinstance(old_state["reported"], dict) or \
       not isinstance(old_state["pending"], bool):
            await runtime.service_registry.call(
                "logger.log",
                level="warning",
                message=f"Device state fields have wrong types: {internal_id}",
                plugin="devices_module",
            )
            return

    prev_state = copy.deepcopy(old_state)

    if isinstance(reported_state, dict):
        old_state["reported"].update(reported_state)

    old_state["pending"] = False

    new_state = old_state

    device["state"] = new_state

    await runtime.storage.set("devices", internal_id, device)

    await runtime.event_bus.publish(
        "internal.device_state_updated",
        {
            "internal_id": internal_id,
            "external_id": external_id,
            "old_state": prev_state,
            "new_state": new_state,
        }
    )
