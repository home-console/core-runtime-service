"""
Device operations — объявлены и принадлежат devices-домену.

Handlers вызывают ТОЛЬКО сервисы devices.*.
Не знают про admin, HTTP, ACL.
"""

from typing import Any, Dict, Optional


async def handle_device_set_state(params: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handler: device.set_state
    Params: device_id (str), state (dict)
    """
    device_id = params.get("device_id")
    state = params.get("state", {})

    if not device_id:
        raise ValueError("device_id is required")

    runtime = context.get("runtime")
    if not runtime:
        raise RuntimeError("Runtime not available in context")

    ctx = runtime.kernel_context
    services = ctx.get_service("service_registry")

    result = await services.call(
        "devices.set_state",
        device_id,
        state,
    )
    return {
        "device_id": device_id,
        "success": True,
        "result": result,
    }


async def handle_device_mapping_create(params: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handler: device.mapping.create
    Params: external_id (str), internal_id (str)
    """
    external_id = params.get("external_id")
    internal_id = params.get("internal_id")

    if not external_id or not internal_id:
        raise ValueError("external_id and internal_id are required")

    runtime = context.get("runtime")
    if not runtime:
        raise RuntimeError("Runtime not available in context")

    ctx = runtime.kernel_context
    services = ctx.get_service("service_registry")

    result = await services.call(
        "devices.create_mapping",
        external_id,
        internal_id,
    )
    return {"success": True, "result": result}


async def handle_device_mapping_delete(params: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handler: device.mapping.delete
    Params: external_id (str)
    """
    external_id = params.get("external_id")

    if not external_id:
        raise ValueError("external_id is required")

    runtime = context.get("runtime")
    if not runtime:
        raise RuntimeError("Runtime not available in context")

    ctx = runtime.kernel_context
    services = ctx.get_service("service_registry")

    result = await services.call(
        "devices.delete_mapping",
        external_id,
    )
    return {"success": True, "result": result}


async def handle_device_mapping_auto(params: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handler: device.mapping.auto
    Params: provider (str, optional)
    """
    provider = params.get("provider")

    runtime = context.get("runtime")
    if not runtime:
        raise RuntimeError("Runtime not available in context")

    ctx = runtime.kernel_context
    services = ctx.get_service("service_registry")

    result = await services.call(
        "devices.auto_map_external",
        provider,
    )
    return {"success": True, "result": result}


def register_device_operations(runtime: Any) -> None:
    """Регистрирует операции devices в OperationManager. Вызывать из DevicesModule.start()."""
    ops = getattr(runtime, "operations", None)
    if not ops:
        return

    ops.register_handler("device.set_state", handle_device_set_state)
    ops.register_handler("device.mapping.create", handle_device_mapping_create)
    ops.register_handler("device.mapping.delete", handle_device_mapping_delete)
    ops.register_handler("device.mapping.auto", handle_device_mapping_auto)
