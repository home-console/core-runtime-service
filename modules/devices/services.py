from typing import Any, Dict, List, Optional
import time

# Константа для определения online статуса устройства
DEVICE_ONLINE_TIMEOUT = 300  # секунд (5 минут)


def _is_device_online(last_seen: Optional[float]) -> bool:
    """
    Определяет, онлайн ли устройство на основе last_seen.
    
    Args:
        last_seen: timestamp последнего контакта или None
        
    Returns:
        True если устройство видели недавно (в пределах DEVICE_ONLINE_TIMEOUT)
    """
    if last_seen is None:
        return False
    
    now = time.time()
    return (now - last_seen) <= DEVICE_ONLINE_TIMEOUT


async def create_device(
    runtime, 
    device_id: str, 
    name: str = "Unknown", 
    device_type: str = "generic",
    owner_id: Optional[str] = None,
    shared_with: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Создаёт новое устройство.
    
    Args:
        runtime: экземпляр CoreRuntime
        device_id: уникальный ID устройства
        name: имя устройства
        device_type: тип устройства
        owner_id: ID владельца (опционально, для ACL)
        shared_with: список user_id с доступом (опционально, для ACL)
    
    Returns:
        Созданное устройство
    """
    if not isinstance(device_id, str) or not device_id:
        raise ValueError("device_id должен быть непустой строкой")

    # Проверяем, существует ли устройство
    existing_device = await runtime.storage.get("devices", device_id)
    now = time.time()
    
    if existing_device is None:
        # Создаём новое устройство
        device = {
            "id": device_id,
            "name": name,
            "type": device_type,
            "state": {
                "desired": {"on": False},
                "reported": {"on": False},
                "pending": False,
            },
            "created_at": now,
            "updated_at": now,
            "last_seen": None,  # Устройство ещё не видели
            "online": False,    # По умолчанию оффлайн
        }
    else:
        # Устройство уже существует - обновляем только поля, не трогая created_at
        device = existing_device.copy()
        device["name"] = name
        device["type"] = device_type
        # Обновляем updated_at, но сохраняем created_at если он есть
        device["updated_at"] = now
        if "created_at" not in device:
            device["created_at"] = now
        # Инициализируем online/offline поля, если их нет
        if "last_seen" not in device:
            device["last_seen"] = None
        if "online" not in device:
            device["online"] = _is_device_online(device.get("last_seen"))
    
    # Добавляем ACL поля, если указаны
    if owner_id:
        device["owner_id"] = owner_id
    if shared_with and isinstance(shared_with, list):
        device["shared_with"] = shared_with

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

    # Извлекаем реальное состояние: если передан { state: { on: ... } }, извлекаем внутренний state
    actual_state = state
    if isinstance(state, dict) and "state" in state and isinstance(state["state"], dict):
        actual_state = state["state"]
    
    if isinstance(actual_state, dict):
        current_state["desired"].update(actual_state)

    current_state["pending"] = True

    device["state"] = current_state
    device["updated_at"] = time.time()

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
            "params": actual_state,  # Передаём извлечённое состояние
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
