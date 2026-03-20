"""
Pending Cleaner — механизм для очистки зависших команд (pending=True) с timeout.

Если команда отправлена на устройство и был установлен pending=True,
но ответ не пришёл в течение PENDING_TIMEOUT_SEC — автоматически сбрасываем pending.
"""

import asyncio
import time
from typing import Any, List, Dict, Optional


PENDING_TIMEOUT_SEC = 60  # Timeout для зависших команд (60 секунд)


async def start_pending_cleaner(runtime: Any) -> None:
    """
    Запустить background task для очистки зависших pending команд.
    
    Периодически проверяет все устройства и:
    - Если pending=True и команда "старше" PENDING_TIMEOUT_SEC
    - Сбрасывает pending=False (команда считается потерянной)
    
    Args:
        runtime: экземпляр CoreRuntime
    """
    
    async def cleanup_loop():
        """Background loop для очистки зависших команд."""
        while True:
            try:
                await asyncio.sleep(10)  # Проверка каждые 10 секунд
                
                # Получаем все устройства
                try:
                    keys = await runtime.storage.list_keys("devices")
                except Exception:
                    continue
                
                now = time.time()
                cleared_count = 0
                
                for device_id in keys:
                    try:
                        device = await runtime.storage.get("devices", device_id)
                        if not isinstance(device, dict):
                            continue
                        
                        state = device.get("state", {})
                        if not isinstance(state, dict):
                            continue
                        
                        # Если pending=True, проверяем timestamp
                        if state.get("pending") is True:
                            # Используем updated_at как время последней команды
                            updated_at = device.get("updated_at", 0)
                            elapsed = now - updated_at
                            
                            # Если команда зависла дольше timeout — очищаем
                            if elapsed > PENDING_TIMEOUT_SEC:
                                state["pending"] = False
                                device["state"] = state
                                device["updated_at"] = now
                                
                                try:
                                    await runtime.storage.set("devices", device_id, device)
                                    cleared_count += 1
                                    
                                    # Логируем очистку
                                    try:
                                        await runtime.kernel_context.get_service("service_registry").call(
                                            "logger.log",
                                            level="warning",
                                            message=f"Cleared hung pending command for device {device_id} (elapsed {elapsed:.1f}s > {PENDING_TIMEOUT_SEC}s)",
                                            module="devices_pending_cleaner",
                                            context={
                                                "device_id": device_id,
                                                "elapsed_sec": elapsed,
                                                "timeout_sec": PENDING_TIMEOUT_SEC,
                                            }
                                        )
                                    except Exception:
                                        pass
                                except Exception:
                                    pass
                    
                    except Exception:
                        # Пропускаем ошибки обработки отдельных устройств
                        pass
                
                # Логируем итоги если что-то было очищено
                if cleared_count > 0:
                    try:
                        await runtime.kernel_context.get_service("service_registry").call(
                            "logger.log",
                            level="info",
                            message=f"Cleaned {cleared_count} hung pending commands",
                            module="devices_pending_cleaner",
                            context={"cleared_count": cleared_count}
                        )
                    except Exception:
                        pass
            
            except Exception as e:
                # Ловим все ошибки чтобы loop не умер
                try:
                    await runtime.kernel_context.get_service("service_registry").call(
                        "logger.log",
                        level="error",
                        message=f"Error in pending cleaner loop: {e}",
                        module="devices_pending_cleaner",
                    )
                except Exception:
                    pass
    
    # Запускаем loop в фоне
    asyncio.create_task(cleanup_loop())


async def get_hung_pending_devices(runtime: Any) -> List[Dict[str, Any]]:
    """
    Получить список устройств с зависшим pending (старше timeout).
    
    Используется для диагностики и admin API.
    
    Returns:
        Список устройств с зависшим pending
    """
    result = []
    now = time.time()
    
    try:
        keys = await runtime.storage.list_keys("devices")
    except Exception:
        return result
    
    for device_id in keys:
        try:
            device = await runtime.storage.get("devices", device_id)
            if not isinstance(device, dict):
                continue
            
            state = device.get("state", {})
            if not isinstance(state, dict):
                continue
            
            # Если pending=True и старое
            if state.get("pending") is True:
                updated_at = device.get("updated_at", 0)
                elapsed = now - updated_at
                
                if elapsed > PENDING_TIMEOUT_SEC:
                    result.append({
                        "device_id": device_id,
                        "elapsed_sec": elapsed,
                        "timeout_sec": PENDING_TIMEOUT_SEC,
                        "device": device,
                    })
        except Exception:
            pass
    
    return result


async def clear_pending_manually(runtime: Any, device_id: str) -> Dict[str, Any]:
    """
    Вручную очистить pending для конкретного устройства.
    
    Используется для явного сброса зависшей команды через API.
    
    Args:
        runtime: экземпляр CoreRuntime
        device_id: идентификатор устройства
    
    Returns:
        Результат: {"ok": bool, "device_id": str, "error": str (опционально)}
    """
    try:
        device = await runtime.storage.get("devices", device_id)
        if device is None:
            return {"ok": False, "error": f"Device {device_id} not found"}
        
        state = device.get("state", {})
        if not isinstance(state, dict):
            return {"ok": False, "error": f"Device {device_id} has invalid state"}
        
        was_pending = state.get("pending") is True
        state["pending"] = False
        device["state"] = state
        device["updated_at"] = time.time()
        
        await runtime.storage.set("devices", device_id, device)
        
        # Логируем
        try:
            await runtime.kernel_context.get_service("service_registry").call(
                "logger.log",
                level="info",
                message=f"Manually cleared pending for device {device_id}",
                module="devices_pending_cleaner",
                context={"device_id": device_id, "was_pending": was_pending}
            )
        except Exception:
            pass
        
        return {
            "ok": True,
            "device_id": device_id,
            "was_pending": was_pending,
            "now_pending": False,
        }
    
    except Exception as e:
        return {"ok": False, "error": str(e)}
