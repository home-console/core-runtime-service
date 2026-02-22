import copy
import time
from modules.devices.services import _is_device_online


async def handle_external_device_discovered(runtime, data: dict) -> None:
    external_id = data.get("external_id")
    if not external_id:
        return

    await runtime.storage.set("devices_external", external_id, data)


async def handle_external_state(runtime, data: dict) -> None:
    # Логируем получение события
    try:
        await runtime.service_registry.call(
            "logger.log",
            level="debug",
            message=f"handle_external_state: received event",
            plugin="devices_module",
            context={"data": data}
        )
    except Exception:
        pass

    external_id = data.get("external_id")
    reported_state = data.get("state")

    if not external_id or reported_state is None:
        try:
            await runtime.service_registry.call(
                "logger.log",
                level="debug",
                message=f"handle_external_state: missing external_id or state",
                plugin="devices_module",
                context={"data": data}
            )
        except Exception:
            pass
        return

    mapping = await runtime.storage.get("devices_mappings", external_id)

    # DEBUG 4: Trace mapping and state flow
    trace_timestamp = time.time()
    
    if not mapping or not isinstance(mapping, dict):
        # Сохраняем pending state на случай если mapping будет создан позже
        # (например, WebSocket обновление пришло ДО auto_map_external)
        try:
            await runtime.storage.set("devices_external_pending_state", external_id, reported_state)
            await runtime.service_registry.call(
                "logger.log",
                level="debug",
                message=f"[STATE_FLOW] Mapping NOT found, storing pending state",
                plugin="devices_module",
                context={
                    "external_id": external_id,
                    "incoming_state": reported_state,
                }
            )
            
            # Save trace
            try:
                await runtime.storage.set(
                    "yandex_debug_state_flow",
                    f"{external_id}_{int(trace_timestamp * 1000)}_pending",
                    {
                        "timestamp": trace_timestamp,
                        "external_id": external_id,
                        "status": "pending_no_mapping",
                        "incoming_state": reported_state,
                    },
                )
            except Exception:
                pass
        except Exception:
            pass
        return

    # DEBUG 4B: Mapping found
    try:
        await runtime.service_registry.call(
            "logger.log",
            level="debug",
            message=f"[STATE_FLOW] Mapping FOUND, applying state",
            plugin="devices_module",
            context={
                "external_id": external_id,
                "internal_id": mapping.get("internal_id"),
                "incoming_state": reported_state,
            }
        )
    except Exception:
        pass

    internal_id = mapping.get("internal_id")
    if not internal_id:
        try:
            await runtime.service_registry.call(
                "logger.log",
                level="debug",
                message=f"handle_external_state: mapping has no internal_id",
                plugin="devices_module",
                context={"mapping": mapping}
            )
        except Exception:
            pass
        return

    device = await runtime.storage.get("devices", internal_id)

    if device is None:
        try:
            await runtime.service_registry.call(
                "logger.log",
                level="debug",
                message=f"handle_external_state: device not found for internal_id={internal_id}",
                plugin="devices_module",
                context={"external_id": external_id}
            )
        except Exception:
            pass
        return

    # Обновляем last_seen и online статус при получении обновления
    now = time.time()
    device["last_seen"] = now
    device["updated_at"] = now
    
    # Определяем онлайн статус на основе last_seen (функция уже импортирована в начале файла)
    old_online = device.get("online")
    device["online"] = _is_device_online(device.get("last_seen"))
    new_online = device.get("online")

    old_state = device.get("state", {})

    if not isinstance(old_state, dict) or \
        not all(k in old_state for k in ["desired", "reported", "pending"]):
        old_state = {"desired": {}, "reported": {}, "pending": False}
        device["state"] = old_state

    # DEBUG 4C: Save full state flow
    try:
        await runtime.storage.set(
            "yandex_debug_state_flow",
            f"{internal_id}_{int(trace_timestamp * 1000)}_apply",
            {
                "timestamp": trace_timestamp,
                "external_id": external_id,
                "internal_id": internal_id,
                "status": "applying",
                "incoming_state": reported_state,
                "old_reported": old_state.get("reported", {}),
                "old_online": old_online,
                "new_online": new_online,
                "online_changed": old_online != new_online,
            },
        )
    except Exception:
        pass

    if not isinstance(old_state, dict) or \
        not all(k in old_state for k in ["desired", "reported", "pending"]):
        old_state = {"desired": {}, "reported": {}, "pending": False}
        device["state"] = old_state

    # Копия состояния до изменений — для события internal.device_state_updated
    prev_state = copy.deepcopy(old_state)

    # ВАЖНО: Обновление из WebSocket - это реальное состояние устройства
    # Оно может прийти от нашей команды ИЛИ от стороннего приложения
    # В любом случае, это актуальное состояние устройства, поэтому:
    # 1. Сбрасываем pending (устройство ответило своим состоянием)
    # 2. Синхронизируем desired с reported (чтобы не было рассинхронизации)
    desired = old_state.get("desired", {})
    reported = old_state.get("reported", {})
    
    # Сравниваем состояния для логирования
    states_match = True
    if isinstance(desired, dict) and isinstance(reported, dict) and desired:
        # Проверяем все поля из desired - они должны совпадать с reported
        for key in desired.keys():
            if key not in reported or reported[key] != desired[key]:
                states_match = False
                break
    elif not desired:
        states_match = True
    else:
        states_match = False
    
    # ВАЖНО: При обновлении из WebSocket всегда сбрасываем pending
    # Это реальное состояние устройства, независимо от того, кто его изменил
    old_state["pending"] = False

    # Применяем входящее состояние к reported (иначе GET /devices вернёт старые данные)
    if isinstance(reported_state, dict) and reported_state:
        rep = old_state.get("reported")
        if isinstance(rep, dict):
            rep.update(reported_state)
        else:
            old_state["reported"] = dict(reported_state)
    
    # Если состояния не совпадают - это значит устройство изменило состояние извне
    # Синхронизируем desired с reported, чтобы не было рассинхронизации
    if not states_match and isinstance(reported_state, dict) and reported_state:
        # Обновляем desired только для полей, которые пришли в обновлении
        # Это нужно, чтобы desired отражал реальное состояние устройства
        if isinstance(desired, dict):
            for key in reported_state.keys():
                if key in reported:
                    desired[key] = reported[key]
            old_state["desired"] = desired
        pending_cleared_reason = "ws_update_synced_desired"
    else:
        pending_cleared_reason = "states_match" if states_match else "ws_update_received"
    
    # Логируем обновление для отладки
    try:
        await runtime.service_registry.call(
            "logger.log",
            level="debug",
            message=f"handle_external_state: processing update",
            plugin="devices_module",
            context={
                "internal_id": internal_id,
                "external_id": external_id,
                "desired": desired,
                "reported_before": old_state.get("reported", {}).copy() if isinstance(reported_state, dict) and reported_state else None,
                "reported_after": old_state.get("reported", {}),
                "reported_update": reported_state,
                "states_match": states_match,
                "pending_cleared": old_state.get("pending") == False,
                "pending_cleared_reason": pending_cleared_reason,
            }
        )
    except Exception:
        pass

    new_state = old_state

    device["state"] = new_state
    device["updated_at"] = time.time()
    
    # Обновляем last_seen и online статус при реальном контакте с устройством
    now = time.time()
    device["last_seen"] = now
    # Функция _is_device_online уже импортирована в начале файла
    device["online"] = _is_device_online(device["last_seen"])

    await runtime.storage.set("devices", internal_id, device)
    
    # Логируем успешное обновление
    try:
        await runtime.service_registry.call(
            "logger.log",
            level="debug",
            message=f"handle_external_state: state updated successfully",
            plugin="devices_module",
            context={
                "internal_id": internal_id,
                "external_id": external_id,
                "pending_cleared": True,
            }
        )
    except Exception:
        pass

    # Логируем успешное обновление
    try:
        await runtime.service_registry.call(
            "logger.log",
            level="debug",
            message=f"handle_external_state: updated device {internal_id}, pending=False",
            plugin="devices_module",
            context={
                "external_id": external_id,
                "reported_state": reported_state,
                "new_state": new_state
            }
        )
    except Exception:
        pass

    await runtime.event_bus.publish(
        "internal.device_state_updated",
        {
            "internal_id": internal_id,
            "external_id": external_id,
            "old_state": prev_state,
            "new_state": new_state,
        }
    )
