from __future__ import annotations

from typing import Any, Dict


async def _execute_marketplace_operation(runtime: Any, op_type: str, params: Dict[str, Any]) -> Dict[str, Any]:
    ops_mgr = getattr(runtime, "operations", None)
    if ops_mgr is None:
        raise RuntimeError("Operations manager not available")

    from core.operations import OperationInitiator, OperationInitiatorKind

    initiator = OperationInitiator(
        kind=OperationInitiatorKind.ADMIN,
        user_id=None,
    )

    operation = await ops_mgr.create(
        op_type=op_type,
        params=params,
        initiator=initiator,
    )

    result = await ops_mgr.execute(operation)
    return result.to_dict()


async def admin_marketplace_install(runtime: Any, body: Any = None, **kwargs: Any) -> Dict[str, Any]:
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ValueError("Request body must be JSON object")
    return await _execute_marketplace_operation(runtime, "marketplace.install", dict(body))


async def admin_marketplace_install_from_registry(runtime: Any, body: Any = None, **kwargs: Any) -> Dict[str, Any]:
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ValueError("Request body must be JSON object")
    return await _execute_marketplace_operation(
        runtime, "marketplace.install_from_registry", dict(body)
    )


async def admin_marketplace_remove(runtime: Any, body: Any = None, **kwargs: Any) -> Dict[str, Any]:
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ValueError("Request body must be JSON object")
    return await _execute_marketplace_operation(runtime, "marketplace.remove", dict(body))


async def admin_marketplace_update(runtime: Any, body: Any = None, **kwargs: Any) -> Dict[str, Any]:
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ValueError("Request body must be JSON object")
    return await _execute_marketplace_operation(runtime, "marketplace.update", dict(body))


async def admin_marketplace_enable(runtime: Any, plugin_name: str, **kwargs: Any) -> Dict[str, Any]:
    return await _execute_marketplace_operation(runtime, "marketplace.enable", {"plugin_name": plugin_name})


async def admin_marketplace_disable(runtime: Any, plugin_name: str, **kwargs: Any) -> Dict[str, Any]:
    return await _execute_marketplace_operation(runtime, "marketplace.disable", {"plugin_name": plugin_name})


async def admin_marketplace_installed(runtime: Any, **kwargs: Any) -> Dict[str, Any]:
    return await _execute_marketplace_operation(runtime, "marketplace.list_installed", {})


async def admin_marketplace_updates(runtime: Any, body: Any = None, **kwargs: Any) -> Dict[str, Any]:
    # Optional body params (e.g. registry_url override) are supported for symmetry.
    params: Dict[str, Any] = {}
    if body is not None:
        if not isinstance(body, dict):
            raise ValueError("Request body must be JSON object")
        params = dict(body)
    return await _execute_marketplace_operation(runtime, "marketplace.check_updates", params)

