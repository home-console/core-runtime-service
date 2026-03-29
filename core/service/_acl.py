"""
ACL builder и типы для ServiceRegistry.

Содержит:
- Type aliases (PreloadResourceFunc, PolicyEngineFactory, ServiceAclWrapperBuilder)
- _default_policy_engine_factory
- _default_acl_wrapper_builder
"""

from typing import Any, Awaitable, Callable, Optional

from core.service.models import ServiceFunc

PreloadResourceFunc = Callable[[tuple[Any, ...], dict[str, Any]], Awaitable[Any]]
PolicyEngineFactory = Callable[[Any | None], Any]
ServiceAclWrapperBuilder = Callable[
    ...,
    tuple[ServiceFunc, bool],
]


def _default_policy_engine_factory(provided: Any | None) -> Any:
    return provided


def _default_acl_wrapper_builder(
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
    _ = service_name
    effective_admin_only = bool(admin_only) if admin_only is not None else False

    async def wrapped(*args: Any, **kwargs: Any) -> Any:
        ctx = (
            policy_engine.current_context()
            if policy_engine is not None and hasattr(policy_engine, "current_context")
            else None
        )

        if (
            effective_admin_only
            and policy_engine is not None
            and hasattr(policy_engine, "enforce_admin")
        ):
            policy_engine.enforce_admin(ctx)

        if inject_owner_param and ctx is not None and kwargs.get(inject_owner_param) is None:
            kwargs[inject_owner_param] = getattr(ctx, "user_id", None)

        if (
            policy_engine is not None
            and resource
            and preload_resource
            and hasattr(policy_engine, "enforce_policy")
        ):
            obj = await preload_resource(args, kwargs)
            policy_engine.enforce_policy(ctx, resource, obj)

        result = await func(*args, **kwargs)

        if (
            policy_engine is not None
            and enforce_result
            and resource
            and hasattr(policy_engine, "enforce_policy")
        ):
            policy_engine.enforce_policy(ctx, resource, result)

        if (
            policy_engine is not None
            and filter_result
            and resource
            and isinstance(result, (list, tuple))
            and hasattr(policy_engine, "filter_with_policy")
        ):
            result = policy_engine.filter_with_policy(ctx, resource, result)

        return result

    return wrapped, effective_admin_only
