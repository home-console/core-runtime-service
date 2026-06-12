"""
Фабрики async-handlers для admin-сервисов с единым маппингом positional/kw args.

Используется вместо десятков локальных closure в `AdminModule` (D3).
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional, Sequence
import logging
logger = logging.getLogger(__name__)


def _pick_kw(kw: dict[str, Any], names: Sequence[str], default: Any = None) -> Any:
    for n in names:
        if n in kw and kw[n] is not None:
            return kw[n]
    return default


def _pick_arg(positional: Sequence[Any], idx: int, default: Any = None) -> Any:
    if idx < 0 or idx >= len(positional):
        return default
    v = positional[idx]
    return default if v is None else v


def normalize_param(
    positional: Sequence[Any],
    kw: dict[str, Any],
    *,
    index: Optional[int] = None,
    names: Sequence[str] = (),
    default: Any = None,
) -> Any:
    """
    Normalize a single param coming from mixed calling conventions:
    - HTTP/router may pass as kwarg (path/query/body/ws)
    - console/tests may pass as positional
    """
    if index is not None:
        v = _pick_arg(positional, index, default=None)
        if v is not None:
            return v
    v = _pick_kw(kw, names, default=None)
    if v is not None:
        return v
    return default


def make_runtime_handler(
    fn: Callable[..., Awaitable[Any]],
    *,
    runtime: Any,
    params: Sequence[tuple[str, Optional[int], Sequence[str], Any]] = (),
) -> Callable[..., Awaitable[Any]]:
    """
    Create an async handler that calls `fn(runtime, **normalized_params)`.

    params:
      (param_name, positional_index, kw_names, default)
    """

    async def handler(*args: Any, **kw: Any) -> Any:
        call_kw: dict[str, Any] = {}
        for name, idx, kw_names, default in params:
            call_kw[name] = normalize_param(
                args,
                kw,
                index=idx,
                names=kw_names,
                default=default,
            )
        return await fn(runtime, **call_kw)

    return handler


def make_runtime_handler_positional(
    fn: Callable[..., Awaitable[Any]],
    *,
    runtime: Any,
    required: Sequence[tuple[Optional[int], Sequence[str]]],
    optional: Sequence[tuple[Optional[int], Sequence[str], Any]] = (),
) -> Callable[..., Awaitable[Any]]:
    """
    Create an async handler that calls `fn(runtime, *args)` after normalizing positional args.
    Used for functions that expect positional parameters (e.g. fn(runtime, id)).
    """

    async def handler(*args: Any, **kw: Any) -> Any:
        call_args: list[Any] = []
        for idx, kw_names in required:
            v = normalize_param(args, kw, index=idx, names=kw_names, default=None)
            call_args.append(v)
        for idx, kw_names, default in optional:
            v = normalize_param(args, kw, index=idx, names=kw_names, default=default)
            call_args.append(v)
        return await fn(runtime, *call_args)

    return handler


def make_service_call_handler_positional(
    *,
    services: Any,
    target_service: str,
    required: Sequence[tuple[Optional[int], Sequence[str]]],
    optional: Sequence[tuple[Optional[int], Sequence[str], Any]] = (),
    unavailable_response: dict[str, Any] | None = None,
) -> Callable[..., Awaitable[Any]]:
    """
    Create an async handler that proxies to ServiceRegistry.call(target_service, *args).

    `required` / `optional` are normalized from mixed calling conventions (positional/kw).
    """

    async def handler(*args: Any, **kw: Any) -> Any:
        if not await services.has_service(target_service):
            return unavailable_response or {
                "ok": False,
                "error": "Service is unavailable",
                "code": "SERVICE_UNAVAILABLE",
            }
        call_args: list[Any] = []
        for idx, kw_names in required:
            call_args.append(normalize_param(args, kw, index=idx, names=kw_names, default=None))
        for idx, kw_names, default in optional:
            call_args.append(normalize_param(args, kw, index=idx, names=kw_names, default=default))
        return await services.call(target_service, *call_args)

    return handler


def make_service_call_handler_kwargs(
    *,
    services: Any,
    target_service: str,
    params: Sequence[tuple[str, Optional[int], Sequence[str], Any]] = (),
    unavailable_response: dict[str, Any] | None = None,
    close_ws_on_unavailable: bool = False,
    ws_param_names: Sequence[str] = ("websocket",),
    ws_close_code: int = 1013,
    ws_close_reason: str = "Service unavailable",
) -> Callable[..., Awaitable[Any]]:
    """
    Create an async handler that proxies to ServiceRegistry.call(target_service, **kwargs).
    """

    async def handler(*args: Any, **kw: Any) -> Any:
        if not await services.has_service(target_service):
            if close_ws_on_unavailable:
                ws = normalize_param(args, kw, index=0, names=ws_param_names, default=None)
                try:
                    if ws is not None:
                        await ws.close(code=ws_close_code, reason=ws_close_reason)
                except Exception:
                    logger.debug("handler_factory.handler: unexpected error (suppressed)", exc_info=True)
                    pass
            return unavailable_response or {
                "ok": False,
                "error": "Service is unavailable",
                "code": "SERVICE_UNAVAILABLE",
            }
        call_kw: dict[str, Any] = {}
        for name, idx, kw_names, default in params:
            call_kw[name] = normalize_param(
                args,
                kw,
                index=idx,
                names=kw_names,
                default=default,
            )
        return await services.call(target_service, **call_kw)

    return handler

