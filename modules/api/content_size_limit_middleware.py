"""
HTTP request size limit middleware.

Security rationale:
- Protects against accidental/intentional huge payloads causing memory pressure (DoS)
- Enforces an upper bound before handlers attempt to parse JSON/body
"""

from __future__ import annotations

from typing import Callable, Iterable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.requests import ClientDisconnect


CSL_DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10 MiB
CSL_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _parse_max_bytes(raw: str | None) -> int:
    if raw is None or not str(raw).strip():
        return CSL_DEFAULT_MAX_BYTES
    try:
        val = int(str(raw).strip())
    except (TypeError, ValueError) as e:
        raise ValueError(f"Invalid integer env var RUNTIME_MAX_REQUEST_BODY_BYTES={raw!r}") from e
    if val <= 0:
        raise ValueError(
            f"RUNTIME_MAX_REQUEST_BODY_BYTES must be positive, got: {raw!r}"
        )
    return val


def _should_check_path(path: str, exclude_prefixes: Iterable[str]) -> bool:
    for p in exclude_prefixes:
        if p and path.startswith(p):
            return False
    return True


async def content_size_limit_middleware(request: Request, call_next: Callable) -> Response:
    import os

    # Only check methods that can carry meaningful bodies
    if request.method in CSL_SAFE_METHODS:
        return await call_next(request)

    # Allow explicit exclusions (comma-separated prefixes)
    exclude_raw = os.getenv("RUNTIME_MAX_REQUEST_BODY_EXCLUDE_PREFIXES", "")
    exclude_prefixes = [x.strip() for x in exclude_raw.split(",") if x.strip()]
    if exclude_prefixes and not _should_check_path(request.url.path, exclude_prefixes):
        return await call_next(request)

    max_bytes = _parse_max_bytes(os.getenv("RUNTIME_MAX_REQUEST_BODY_BYTES"))

    # Fast path: Content-Length header
    cl = request.headers.get("content-length")
    if cl:
        try:
            length = int(cl)
            if length > max_bytes:
                return JSONResponse(
                    status_code=413,
                    content={
                        "detail": "Request body too large",
                        "max_bytes": max_bytes,
                        "content_length": length,
                    },
                )
        except (TypeError, ValueError):
            # Ignore invalid header; fallback to reading body size below.
            pass

    # Fallback: read body and enforce size. Starlette caches request.body() so downstream
    # handlers will still be able to read it.
    try:
        body = await request.body()
    except ClientDisconnect:
        # Client gave up before sending the body; nothing left to enforce or respond to.
        return Response(status_code=499)
    if body and len(body) > max_bytes:
        return JSONResponse(
            status_code=413,
            content={
                "detail": "Request body too large",
                "max_bytes": max_bytes,
                "content_length": len(body),
            },
        )

    return await call_next(request)

