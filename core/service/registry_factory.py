"""
ServiceRegistry factory — выбор реализации по конфигурации.

ENV:
    SERVICE_REGISTRY_BACKEND=local|remote  (default: local)
    CORE_RUNTIME_URL=http://core-runtime:8000
    INTERNAL_API_KEY=secret
    SERVICE_CALL_TIMEOUT=30
"""

from __future__ import annotations

import os
from typing import Any

from core.ports import IServiceRegistry


def create_service_registry(
    config: Any = None,
    *,
    policy_engine: Any | None = None,
    policy_engine_factory: Any | None = None,
    acl_wrapper_builder: Any | None = None,
) -> IServiceRegistry:
    backend = os.getenv("SERVICE_REGISTRY_BACKEND", "local").lower().strip()

    if backend == "remote":
        base_url = os.getenv("CORE_RUNTIME_URL", "http://localhost:8000").strip()
        api_key = (os.getenv("INTERNAL_API_KEY", "") or "").strip()
        timeout = float(os.getenv("SERVICE_CALL_TIMEOUT", "30"))

        if not api_key:
            raise RuntimeError(
                "INTERNAL_API_KEY required when SERVICE_REGISTRY_BACKEND=remote"
            )

        from core.service.remote_registry import RemoteServiceRegistry

        return RemoteServiceRegistry(
            base_url=base_url,
            api_key=api_key,
            default_timeout=timeout,
        )

    from core.service.registry import ServiceRegistry

    default_timeout = getattr(config, "service_call_timeout", None) if config else None
    return ServiceRegistry(
        default_timeout=default_timeout,
        policy_engine=policy_engine,
        policy_engine_factory=policy_engine_factory,
        acl_wrapper_builder=acl_wrapper_builder,
    )

