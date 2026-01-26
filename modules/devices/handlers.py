import copy
import time


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

    if not mapping or not isinstance(mapping, dict):
        try:
            await runtime.service_registry.call(
                "logger.log",
                level="debug",
                message=f"handle_external_state: no mapping found for external_id={external_id}",
                plugin="devices_module",
            )
        except Exception:
            pass
        return

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

    # Обновляем reported если есть данные
    if isinstance(reported_state, dict) and reported_state:
        old_state["reported"].update(reported_state)
    
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
    # Импортируем функцию для определения online статуса
    from .services import _is_device_online
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
