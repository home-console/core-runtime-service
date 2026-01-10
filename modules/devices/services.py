from typing import Any, Dict, List, Optional


async def create_device(runtime, device_id: str, name: str = "Unknown", device_type: str = "generic") -> Dict[str, Any]:
    if not isinstance(device_id, str) or not device_id:
        raise ValueError("device_id должен быть непустой строкой")

    device = {
        "id": device_id,
        "name": name,
        "type": device_type,
        "state": {
            "desired": {"on": False},
            "reported": {"on": False},
            "pending": False,
        },
    }

    await runtime.storage.set("devices", device_id, device)

    return device


async def set_state(runtime, device_id: str, state: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(device_id, str) or not device_id:
        raise ValueError("device_id должен быть непустой строкой")

    device = await runtime.storage.get("devices", device_id)
    if device is None:
        raise ValueError(f"device {device_id} not found")

    current_state = device.get("state", {})

    if not isinstance(current_state, dict) or \
       not all(k in current_state for k in ["desired", "reported", "pending"]):
        raise ValueError(
            f"Device {device_id} has invalid state format. "
            f"Expected: {{desired, reported, pending}}, "
            f"got: {current_state}"
        )

    if not isinstance(current_state["desired"], dict) or \
       not isinstance(current_state["reported"], dict) or \
       not isinstance(current_state["pending"], bool):
        raise ValueError(
            f"Device {device_id} state fields have wrong types. "
            f"Expected: {{desired: dict, reported: dict, pending: bool}}"
        )

    if isinstance(state, dict):
        current_state["desired"].update(state)

    current_state["pending"] = True

    device["state"] = current_state

    await runtime.storage.set("devices", device_id, device)

    external_id = None
    keys = await runtime.storage.list_keys("devices_mappings")
    for k in keys:
        v = await runtime.storage.get("devices_mappings", k)
        # v теперь dict с ключом "internal_id"
        if isinstance(v, dict) and v.get("internal_id") == device_id:
            external_id = k
            break

    await runtime.event_bus.publish(
        "internal.device_command_requested",
        {
            "internal_id": device_id,
            "external_id": external_id,
            "command": "set_state",
            "params": state,
        }
    )

    return {"ok": True, "queued": True, "external_id": external_id, "state": current_state}


async def list_devices(runtime) -> List[Dict[str, Any]]:
    keys = await runtime.storage.list_keys("devices")

    devices: List[Dict[str, Any]] = []
    for dev_id in keys:
        device = await runtime.storage.get("devices", dev_id)
        if device is not None:
            devices.append(device)

    return devices


async def get_device(runtime, device_id: str) -> Dict[str, Any]:
    if not isinstance(device_id, str) or not device_id:
        raise ValueError("device_id должен быть непустой строкой")

    device = await runtime.storage.get("devices", device_id)
    if device is None:
        raise ValueError(f"Устройство с id='{device_id}' не найдено")

    return device


async def list_external(runtime, provider: Optional[str] = None) -> List[Dict[str, Any]]:
    keys = await runtime.storage.list_keys("devices_external")

    out: List[Dict[str, Any]] = []
    for ext_id in keys:
        payload = await runtime.storage.get("devices_external", ext_id)
        if payload is None:
            continue
        if provider is not None:
            if payload.get("provider") != provider:
                continue
        out.append({"external_id": ext_id, "payload": payload})

    return out


async def create_mapping(runtime, external_id: str, internal_id: str) -> Dict[str, Any]:
    if not external_id or not internal_id:
        raise ValueError("external_id и internal_id должны быть непустыми")

    # Сохраняем dict согласно контракту Storage API
    await runtime.storage.set("devices_mappings", external_id, {"internal_id": internal_id})

    return {"ok": True, "external_id": external_id, "internal_id": internal_id}


async def list_mappings(runtime) -> List[Dict[str, Any]]:
    keys = await runtime.storage.list_keys("devices_mappings")

    out: List[Dict[str, Any]] = []
    for k in keys:
        v = await runtime.storage.get("devices_mappings", k)
        # v теперь dict с ключом "internal_id"
        if isinstance(v, dict) and "internal_id" in v:
            out.append({"external_id": k, "internal_id": v["internal_id"]})

    return out


async def delete_mapping(runtime, external_id: str) -> Dict[str, Any]:
    if not external_id:
        return {"ok": False, "error": "external_id required"}

    deleted = await runtime.storage.delete("devices_mappings", external_id)

    return {"ok": bool(deleted), "external_id": external_id}


async def auto_map_external(runtime, provider: Optional[str] = None) -> Dict[str, Any]:
    created = 0
    skipped = 0
    errors: List[str] = []

    externals = await list_external(runtime, provider)

    for item in externals:
        ext_id = item.get("external_id")
        payload = item.get("payload", {})

        if not ext_id:
            continue

        existing = await runtime.storage.get("devices_mappings", ext_id)

        # existing теперь dict или None
        if existing is not None:
            skipped += 1
            continue

        internal_id = f"device-{ext_id}"
        name = None

        if isinstance(payload, dict):
            name = payload.get("name") or payload.get("title")

        if not name:
            device_type = payload.get("type", "device") if isinstance(payload, dict) else "device"
            name = f"{device_type} ({ext_id[:8]})"

        device_type = payload.get("type", "generic") if isinstance(payload, dict) else "generic"

        await create_device(runtime, internal_id, name, device_type)

        try:
            dev = await runtime.storage.get("devices", internal_id)
            if not dev:
                raise
        except Exception as ce:
            errors.append(f"create_failed:{ext_id}:{ce}")
            continue

        # Сохраняем dict согласно контракту Storage API
        await runtime.storage.set("devices_mappings", ext_id, {"internal_id": internal_id})
        created += 1

    return {"ok": True, "created": created, "skipped": skipped, "errors": errors}
