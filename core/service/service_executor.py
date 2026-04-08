from __future__ import annotations

import asyncio
from typing import Any, Optional

from core.service.models import ServiceFunc, ServiceMiddleware
from core.exception_groups import BEST_EFFORT_BACKGROUND_ERRORS


class ServiceExecutor:
    """Executes service handlers with middleware and timeout controls."""

    def __init__(self, default_timeout: Optional[float] = None) -> None:
        self._default_timeout = default_timeout

    async def invoke_with_middleware(
        self,
        service_name: str,
        func: ServiceFunc,
        middleware: list[ServiceMiddleware],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        for item in middleware:
            await item.before_call(service_name, args, kwargs)

        try:
            result = await func(*args, **kwargs)
        except BEST_EFFORT_BACKGROUND_ERRORS as error:
            for item in middleware:
                await item.on_error(service_name, error)
            raise

        for item in middleware:
            await item.after_call(service_name, result)
        return result

    def wrap_with_middleware(
        self,
        service_name: str,
        func: ServiceFunc,
        middleware: list[ServiceMiddleware],
    ) -> ServiceFunc:
        async def wrapped(*args: Any, **kwargs: Any) -> Any:
            return await self.invoke_with_middleware(
                service_name,
                func,
                middleware,
                *args,
                **kwargs,
            )

        return wrapped

    async def execute(
        self,
        service_name: str,
        func: ServiceFunc,
        middleware: list[ServiceMiddleware],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if self._default_timeout is not None:
            return await asyncio.wait_for(
                self.invoke_with_middleware(
                    service_name,
                    func,
                    middleware,
                    *args,
                    **kwargs,
                ),
                timeout=self._default_timeout,
            )

        return await self.invoke_with_middleware(
            service_name,
            func,
            middleware,
            *args,
            **kwargs,
        )

    async def execute_without_timeout(
        self,
        service_name: str,
        func: ServiceFunc,
        middleware: list[ServiceMiddleware],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        return await self.invoke_with_middleware(
            service_name,
            func,
            middleware,
            *args,
            **kwargs,
        )

    async def execute_with_timeout(
        self,
        timeout: float,
        service_name: str,
        func: ServiceFunc,
        middleware: list[ServiceMiddleware],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        return await asyncio.wait_for(
            self.invoke_with_middleware(
                service_name,
                func,
                middleware,
                *args,
                **kwargs,
            ),
            timeout=timeout,
        )

