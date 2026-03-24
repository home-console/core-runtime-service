from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from core.exceptions.errors import ForbiddenError
from core.service.models import ServiceFunc

PreloadResourceFunc = Callable[[tuple[Any, ...], dict[str, Any]], Awaitable[Any]]
PUBLIC_ADMIN_SERVICES = {
    "admin.auth.initialize",
    "admin.auth.login",
    "admin.auth.me",
    "admin.auth.refresh",
}

ADMIN_ONLY_INFRA_SERVICES = {
    "request_logger.get_request_logs",
    "request_logger.list_requests",
    "request_logger.clear_logs",
}


def create_default_policy_engine(provided: Any | None) -> Any:
    if provided is not None:
        return provided
    from modules.policy.engine import PolicyEngine

    return PolicyEngine()


def _resolve_effective_admin_only(
    service_name: str,
    admin_only: Optional[bool],
) -> bool:
    if admin_only is not None:
        return bool(admin_only)

    if service_name.startswith("admin."):
        return service_name not in PUBLIC_ADMIN_SERVICES

    if service_name in ADMIN_ONLY_INFRA_SERVICES:
        return True

    return False


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
            if (
                ctx is not None
                and owner_value is not None
                and not policy_engine.is_privileged(ctx)
                and getattr(ctx, "user_id", None) != owner_value
            ):
                raise ForbiddenError("forbidden")

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
