from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from core.service.models import ServiceFunc

PreloadResourceFunc = Callable[[tuple[Any, ...], dict[str, Any]], Awaitable[Any]]


def create_default_policy_engine(provided: Any | None) -> Any:
    if provided is not None:
        return provided
    from core.policy.engine import PolicyEngine

    return PolicyEngine()


def _resolve_effective_admin_only(
    service_name: str,
    admin_only: Optional[bool],
) -> bool:
    _ = service_name
    return bool(admin_only) if admin_only is not None else False


def build_service_acl_wrapper(
    *,
    policy_engine: Any,
    service_name: str,
    func: ServiceFunc,
    resource: Optional[str],
    admin_only: Optional[bool],
    filter_result: bool,
    enforce_result: bool,
    preload_resource: Optional[PreloadResourceFunc],
    inject_owner_param: Optional[str],
) -> tuple[ServiceFunc, bool]:
    effective_admin_only = _resolve_effective_admin_only(service_name, admin_only)

    async def wrapped(*args: Any, **kwargs: Any) -> Any:
        ctx = policy_engine.current_context()

        if effective_admin_only:
            policy_engine.enforce_admin(ctx)

        if inject_owner_param:
            owner_value = kwargs.get(inject_owner_param)
            if ctx is not None and owner_value is None:
                owner_value = getattr(ctx, "user_id", None)
                kwargs[inject_owner_param] = owner_value

        if resource and preload_resource:
            obj = await preload_resource(args, kwargs)
            policy_engine.enforce_policy(ctx, resource, obj)

        result = await func(*args, **kwargs)

        if enforce_result and resource:
            policy_engine.enforce_policy(ctx, resource, result)

        if filter_result and resource and isinstance(result, (list, tuple)):
            result = policy_engine.filter_with_policy(ctx, resource, result)

        return result

    return wrapped, effective_admin_only
