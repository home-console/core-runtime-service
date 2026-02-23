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


def _apply_capability_driven_state(
    device_state: Dict[str, Any],
    state_update: Dict[str, Any],
    *,
    has_on_off: bool,
    sensor_instances: Optional[set] = None,
) -> Dict[str, Any]:
    """
    Нормализует desired/reported исходя из capability-модели.

    Правила:
    - ключ "on" создаётся только если есть capability on_off;
    - instance из sensor-only (properties) пишется только в reported;
    - остальные ключи (range/mode/и т.п.) пишутся и в desired, и в reported;
    - существующие ключи не удаляются, только обновляются.
    """
    if not isinstance(state_update, dict) or not state_update:
        return device_state

    if not isinstance(device_state, dict):
        device_state = {}

    desired = device_state.get("desired")
    reported = device_state.get("reported")

    if not isinstance(desired, dict):
        desired = {}
    if not isinstance(reported, dict):
        reported = {}

    sensor_instances = sensor_instances or set()

    for key, value in state_update.items():
        # on/off только для устройств с capability on_off
        if key == "on":
            if has_on_off:
                desired["on"] = value
                reported["on"] = value
            # Если on_off нет — не создаём универсальный on
            continue

        # Значения, соответствующие sensor-only (properties), пишем только в reported
        if key in sensor_instances:
            reported[key] = value
            continue

        # Все остальные ключи (range/mode/и т.п.) считаем управляемыми
        desired[key] = value
        reported[key] = value

    device_state["desired"] = desired
    device_state["reported"] = reported
    # Входящее обновление не помечаем как pending
    if "pending" not in device_state or not isinstance(device_state["pending"], bool):
        device_state["pending"] = False

    return device_state


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
            # Изначально состояние пустое, без универсальных ключей
            "state": {
                "desired": {},
                "reported": {},
                "pending": False,
            },
            "created_at": now,
            "updated_at": now,
            "last_seen": None,       # Устройство ещё не видели
            "online": False,         # По умолчанию оффлайн
            "last_ws_update": None,  # Последнее подтверждённое обновление из WebSocket
            # Поля для домов/комнат (опционально)
            "home_id": None,
            "home_name": None,
            "room_id": None,
            "room_name": None,
            "icon_url": None,
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
        # Инициализируем last_ws_update, если его нет
        if "last_ws_update" not in device:
            device["last_ws_update"] = None
        # Инициализируем поля домов/комнат, если их нет
        if "home_id" not in device:
            device["home_id"] = None
        if "home_name" not in device:
            device["home_name"] = None
        if "room_id" not in device:
            device["room_id"] = None
        if "room_name" not in device:
            device["room_name"] = None
        if "icon_url" not in device:
            device["icon_url"] = None

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

    # Нормализуем структуру state (устройства из синка/legacy могут не иметь desired/reported/pending)
    if not isinstance(current_state, dict) or not all(k in current_state for k in ["desired", "reported", "pending"]):
        reported = current_state if isinstance(current_state, dict) else {}
        if not isinstance(reported, dict):
            reported = {}
        current_state = {
            "desired": dict(reported),
            "reported": dict(reported),
            "pending": False,
        }
        device["state"] = current_state

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
            # Гарантируем поле id для клиента (ключ storage может не совпадать с полем в документе)
            out = dict(device)
            if "id" not in out:
                out["id"] = dev_id
            devices.append(out)

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


async def get_external_for_device(runtime, internal_id: str) -> Optional[Dict[str, Any]]:
    """
    Для внутреннего устройства вернуть внешний объект (Яндекс и т.д.), если есть маппинг.

    Returns:
        {"external_id": str, "payload": dict} или None, если маппинга нет.
    """
    if not internal_id:
        return None
    mappings = await list_mappings(runtime)
    for m in mappings:
        if isinstance(m, dict) and m.get("internal_id") == internal_id:
            ext_id = m.get("external_id")
            if not ext_id:
                continue
            payload = await runtime.storage.get("devices_external", ext_id)
            if payload is not None:
                return {"external_id": ext_id, "payload": payload}
            return {"external_id": ext_id, "payload": None}
    return None


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

        # Создаем устройство
        device = await create_device(runtime, internal_id, name, device_type)
        
        # Обновляем информацию о доме/комнате, если есть
        if isinstance(payload, dict):
            if "home_id" in payload:
                device["home_id"] = payload["home_id"]
            if "home_name" in payload:
                device["home_name"] = payload["home_name"]
            if "room_id" in payload:
                device["room_id"] = payload["room_id"]
            if "room_name" in payload:
                device["room_name"] = payload["room_name"]
            if "online" in payload:
                device["online"] = payload["online"]
            if "icon_url" in payload:
                device["icon_url"] = payload["icon_url"]

            # Сохраняем обновленное устройство
            await runtime.storage.set("devices", internal_id, device)
            
            # Синхронизируем initial state и capabilities из external device
            external_state = payload.get("state", {}) or {}
            external_capabilities = payload.get("capabilities", []) or []
            external_properties = payload.get("properties", []) or []

            # Нормализуем список capability-имен (строки) для on_off/range/mode
            capability_names = set()
            for cap in external_capabilities:
                if isinstance(cap, str):
                    name = cap.split(".")[-1]
                elif isinstance(cap, dict):
                    cap_type = cap.get("type") or ""
                    name = cap_type.split(".")[-1] if cap_type else ""
                else:
                    continue
                if name:
                    capability_names.add(name)

            has_on_off = "on_off" in capability_names

            # Вычисляем sensor-only instances из properties (датчики)
            sensor_instances = set()
            for prop in external_properties:
                if not isinstance(prop, dict):
                    continue
                params = prop.get("parameters") or {}
                if isinstance(params, dict):
                    instance = params.get("instance")
                    if isinstance(instance, str) and instance:
                        sensor_instances.add(instance)

            if isinstance(external_state, dict) and external_state:
                # Подготавливаем state структуру
                device_state = device.get("state", {})
                device_state = _apply_capability_driven_state(
                    device_state,
                    external_state,
                    has_on_off=has_on_off,
                    sensor_instances=sensor_instances,
                )

                # Вызываем update_device_fields через service_registry
                try:
                    await runtime.service_registry.call(
                        "devices.update_device_fields",
                        internal_id,
                        {
                            "state": device_state,
                            "capabilities": external_capabilities if isinstance(external_capabilities, list) else [],
                        },
                    )
                except Exception:
                    # Ошибку логируем но продолжаем - устройство всё равно создано
                    pass

        try:
            dev = await runtime.storage.get("devices", internal_id)
            if not dev:
                raise
        except Exception as ce:
            errors.append(f"create_failed:{ext_id}:{ce}")
            continue

        # Сохраняем dict согласно контракту Storage API
        await runtime.storage.set("devices_mappings", ext_id, {"internal_id": internal_id})
        
        # Проверяем есть ли pending state (пришло через WebSocket ДО создания маппинга)
        try:
            pending_state = await runtime.storage.get("devices_external_pending_state", ext_id)
            if pending_state and isinstance(pending_state, dict):
                # Применяем pending state обновления через ту же capability-driven модель
                device_state = device.get("state", {})
                device_state = _apply_capability_driven_state(
                    device_state,
                    pending_state,
                    has_on_off=has_on_off,
                    sensor_instances=sensor_instances,
                )

                # Применяем через update_device_fields
                await runtime.service_registry.call(
                    "devices.update_device_fields",
                    internal_id,
                    {"state": device_state},
                )
                
                # Удаляем pending запись
                try:
                    await runtime.storage.delete("devices_external_pending_state", ext_id)
                except Exception:
                    pass
        except Exception:
            # Ошибку при обработке pending state игнорируем
            # устройство уже создано и будет обновлено через WebSocket позже
            pass
        
        created += 1

    return {"ok": True, "created": created, "skipped": skipped, "errors": errors}

async def get_hung_pending_devices(runtime) -> Dict[str, Any]:
    """
    Get list of devices with hung pending commands (older than timeout).
    
    Used for diagnostics and admin dashboard.
    """
    from .pending_cleaner import get_hung_pending_devices as _get_hung
    
    hung = await _get_hung(runtime)
    return {
        "ok": True,
        "hung_devices": [
            {
                "device_id": item["device_id"],
                "elapsed_sec": item["elapsed_sec"],
                "timeout_sec": item["timeout_sec"],
                "device_name": item["device"].get("name"),
                "device_type": item["device"].get("type"),
                "state": item["device"].get("state", {}),
            }
            for item in hung
        ],
        "total_hung": len(hung),
    }


async def clear_pending_device(runtime, device_id: str) -> Dict[str, Any]:
    """
    Manually clear pending flag for a device.
    
    Used to reset hung commands via admin API.
    """
    from .pending_cleaner import clear_pending_manually
    
    return await clear_pending_manually(runtime, device_id)


async def update_device_fields(runtime, device_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    """
    Update specific fields of a device (online, pending, last_seen, etc).
    
    Used by plugins to update device state without full object replacement.
    
    Args:
        runtime: CoreRuntime instance
        device_id: Device ID
        updates: Dict with fields to update
    
    Returns:
        Updated device
    """
    device = await runtime.storage.get("devices", device_id)
    if device is None:
        raise ValueError(f"device {device_id} not found")
    
    # DEBUG 3: Capture old state for diff
    import copy
    import time as time_module
    
    old_device = copy.deepcopy(device)
    old_state = old_device.get("state", {})
    old_online = old_device.get("online")
    
    # Аккуратный merge, без затирания вложенных numeric/state полей
    for key, value in updates.items():
        if key == "state" and isinstance(value, dict):
            existing_state = device.get("state", {})
            if not isinstance(existing_state, dict):
                existing_state = {}

            incoming_state = value
            new_state: Dict[str, Any] = dict(existing_state)

            # Отдельно мержим desired/reported, не удаляя отсутствующие ключи
            for sub_key in ("desired", "reported"):
                incoming_sub = incoming_state.get(sub_key)
                if isinstance(incoming_sub, dict):
                    existing_sub = new_state.get(sub_key)
                    if not isinstance(existing_sub, dict):
                        existing_sub = {}
                    existing_sub.update(incoming_sub)
                    new_state[sub_key] = existing_sub

            # pending — скалярный флаг
            if "pending" in incoming_state:
                new_state["pending"] = bool(incoming_state.get("pending"))

            # Прочие ключи state (например, агрегированные поля) — простое обновление
            for sk, sv in incoming_state.items():
                if sk in ("desired", "reported", "pending"):
                    continue
                new_state[sk] = sv

            device["state"] = new_state
        else:
            # Прочие поля (online, last_seen, capabilities, last_ws_update и т.п.) обновляем как есть
            device[key] = value

    await runtime.storage.set("devices", device_id, device)
    
    # DEBUG 3B: Log write diff
    try:
        new_state = device.get("state", {})
        new_online = device.get("online")
        
        # Compute state diff
        state_diff = {}
        if isinstance(old_state, dict) and isinstance(new_state, dict):
            for key in set(list(old_state.keys()) + list(new_state.keys())):
                old_val = old_state.get(key)
                new_val = new_state.get(key)
                if old_val != new_val:
                    state_diff[key] = {"old": old_val, "new": new_val}
        
        if state_diff or old_online != new_online:
            await runtime.service_registry.call(
                "logger.log",
                level="debug",
                message=f"[DEVICE_WRITE] Fields updated",
                context={
                    "device_id": device_id,
                    "state_changes": len(state_diff),
                    "online_changed": old_online != new_online,
                    "new_online": new_online,
                    "state_diff_keys": list(state_diff.keys()),
                },
            )
        
        # Save full diff to debug namespace
        await runtime.storage.set(
            "yandex_debug_device_writes",
            f"{device_id}_{int(time_module.time() * 1000)}",
            {
                "timestamp": time_module.time(),
                "device_id": device_id,
                "old_state": old_state,
                "new_state": new_state,
                "state_diff": state_diff,
                "old_online": old_online,
                "new_online": new_online,
            },
        )
    except Exception:
        pass
    
    # DEBUG: log final state after save
    try:
        await runtime.service_registry.call(
            "logger.log",
            level="debug",
            message=f"[update_device_fields] Device state updated and saved",
            context={
                "device_id": device_id,
                "final_state": device.get("state"),
            },
        )
    except Exception:
        pass
    
    return device