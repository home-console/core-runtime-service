"""
Операции Yandex Smart Home — объявлены и принадлежат плагину yandex_smart_home.

Handlers вызывают ТОЛЬКО сервисы плагина (yandex.sync_devices, yandex.check_devices_online).
Не знают про admin, HTTP, ACL.
"""
from typing import Any, Dict


async def handle_yandex_sync(params: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handler: yandex.sync_devices
    Params: (empty или произвольные)
    """
    runtime = context.get("runtime")
    if not runtime:
        raise RuntimeError("Runtime not available in context")

    result = await runtime.service_registry.call("yandex.sync_devices")

    # Сервис возвращает список устройств; оборачиваем в dict для operation result
    if isinstance(result, list):
        return {"success": True, "devices": result, "count": len(result)}
    return {"success": True, "result": result}


async def handle_yandex_check_devices_online(params: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handler: yandex.check_devices_online
    Params: (empty или произвольные)
    """
    runtime = context.get("runtime")
    if not runtime:
        raise RuntimeError("Runtime not available in context")

    result = await runtime.service_registry.call("yandex.check_devices_online")

    if isinstance(result, dict):
        return {"success": True, **result}
    return {"success": True, "result": result}


def register_yandex_operations(runtime: Any) -> None:
    """Регистрирует операции Yandex в OperationManager. Вызывать из on_start() плагина."""
    ops = getattr(runtime, "operations", None)
    if not ops:
        return

    ops.register_handler("yandex.sync_devices", handle_yandex_sync)
    ops.register_handler("yandex.check_devices_online", handle_yandex_check_devices_online)
